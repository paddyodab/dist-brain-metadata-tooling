#!/usr/bin/env python3
"""Tests for constraint ADRs: frontmatter parsing + the rung-3 gate runner.
Run: python3 engine/test_check_constraints.py

Discriminating specs:
  * A bare record ADR (no frontmatter) keeps its historic node shape (id/title/intent/
    status), only gaining kind='record'. Frontmatter junk never leaks into title/intent.
  * Only accepted constraints are enforced. A deterministic gate that exits nonzero —
    or is missing, or absent on a deterministic ADR — fails the build (fail-closed).
  * advisory/semantic are reported, never a failure.
"""
from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

import check_constraints
from extract import adr_nodes, split_frontmatter


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(text))


RECORD_ADR = """\
# 1. Resolution does not record clicks

**Status:** Accepted · 2026-06-18

## Decision

`resolve()` is a pure lookup and never mutates state.

## Consequences

- Read-only callers can resolve freely.
"""

# A deterministic constraint whose gate just echoes its own exit code from a file.
GATE_TPL = """\
import os, sys
from pathlib import Path
root = Path(os.environ.get("GITHUB_WORKSPACE") or ".")
sys.exit(int((root / "gate_rc.txt").read_text().strip()))
"""


def _constraint(title, *, status="accepted", enforcement="advisory", gate=None,
                applies_to=None) -> str:
    fm = [f"title: {title}", f"status: {status}", "kind: constraint",
          f"enforcement: {enforcement}"]
    if gate:
        fm.append(f"gate: {gate}")
    if applies_to:
        fm.append(f"applies_to: {applies_to}")
    front = "\n".join(fm)
    return f"---\n{front}\n---\n# {title}\n\n## Decision\n\nThe rule body.\n"


class FrontmatterTests(unittest.TestCase):
    def test_no_fence_passes_through(self):
        self.assertEqual(split_frontmatter("# Title\n\nbody"), ({}, "# Title\n\nbody"))

    def test_unterminated_fence_is_not_frontmatter(self):
        fm, body = split_frontmatter("---\nkey: v\n# no closing fence")
        self.assertEqual(fm, {})
        self.assertTrue(body.startswith("---"))

    def test_parses_known_keys_and_strips_quotes(self):
        fm, body = split_frontmatter('---\nkind: constraint\napplies_to: "a, b"\n---\nbody')
        self.assertEqual(fm["kind"], "constraint")
        self.assertEqual(fm["applies_to"], "a, b")
        self.assertEqual(body, "body")


class RecordAdrRegressionTests(unittest.TestCase):
    def test_bare_record_adr_keeps_shape(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _write(root, "decisions/0001-resolve.md", RECORD_ADR)
            (node,) = adr_nodes(root)
            self.assertEqual(node["id"], "decision:0001-resolve")
            self.assertEqual(node["title"], "1. Resolution does not record clicks")
            self.assertEqual(node["intent"], "`resolve()` is a pure lookup and never mutates state.")
            self.assertEqual(node["facts"]["status"], "Accepted · 2026-06-18")
            # New, additive: kind defaults to record; no constraint fields leak in.
            self.assertEqual(node["facts"]["kind"], "record")
            self.assertNotIn("enforcement", node["facts"])

    def test_constraint_frontmatter_lands_in_facts(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _write(root, "decisions/0007-pact.md",
                   _constraint("Use Pact", enforcement="deterministic",
                               gate="checks/g.py", applies_to="service boundaries"))
            (node,) = adr_nodes(root)
            f = node["facts"]
            self.assertEqual(f["kind"], "constraint")
            self.assertEqual(f["enforcement"], "deterministic")
            self.assertEqual(f["gate"], "checks/g.py")
            self.assertEqual(f["applies_to"], "service boundaries")
            # Title/intent come from the body, not the frontmatter fence.
            self.assertEqual(node["title"], "Use Pact")
            self.assertEqual(node["intent"], "The rule body.")


class GateRunnerTests(unittest.TestCase):
    def _root_with_gate(self, d, rc: int, **kw) -> Path:
        root = Path(d)
        _write(root, "decisions/0007-pact.md",
               _constraint("Use Pact", enforcement="deterministic", gate="checks/g.py", **kw))
        _write(root, "checks/g.py", GATE_TPL)
        (root / "gate_rc.txt").write_text(str(rc))
        return root

    def test_passing_gate(self):
        with tempfile.TemporaryDirectory() as d:
            res = check_constraints.check_constraints(self._root_with_gate(d, 0))
            self.assertEqual(res["failures"], [])
            self.assertEqual(res["checked"], 1)

    def test_failing_gate_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            res = check_constraints.check_constraints(self._root_with_gate(d, 1))
            self.assertEqual(len(res["failures"]), 1)
            self.assertEqual(res["failures"][0][0], "decision:0007-pact")

    def test_missing_gate_script_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _write(root, "decisions/0007-pact.md",
                   _constraint("Use Pact", enforcement="deterministic", gate="checks/nope.py"))
            res = check_constraints.check_constraints(root)
            self.assertEqual(len(res["failures"]), 1)
            self.assertIn("not found", res["failures"][0][2])

    def test_deterministic_without_gate_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _write(root, "decisions/0007.md", _constraint("Use Pact", enforcement="deterministic"))
            res = check_constraints.check_constraints(root)
            self.assertEqual(len(res["failures"]), 1)
            self.assertIn("no gate", res["failures"][0][2])

    def test_proposed_constraint_is_inert(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._root_with_gate(d, 1)  # gate would fail if run
            # flip status to proposed → not enforced at all
            p = root / "decisions/0007-pact.md"
            p.write_text(p.read_text().replace("status: accepted", "status: proposed"))
            res = check_constraints.check_constraints(root)
            self.assertEqual(res, {"failures": [], "advisories": [], "checked": 0, "total": 0})

    def test_advisory_and_semantic_are_reported_not_failed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _write(root, "decisions/0008-mono.md", _constraint("Monorepo", enforcement="advisory"))
            _write(root, "decisions/0009-comp.md", _constraint("Composition", enforcement="semantic"))
            res = check_constraints.check_constraints(root)
            self.assertEqual(res["failures"], [])
            self.assertEqual(res["checked"], 0)
            kinds = sorted(enf for _, _, enf in res["advisories"])
            self.assertEqual(kinds, ["advisory", "semantic"])

    def test_record_adr_is_not_a_constraint(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _write(root, "decisions/0001-resolve.md", RECORD_ADR)
            res = check_constraints.check_constraints(root)
            self.assertEqual(res["total"], 0)


class ShippedExampleTests(unittest.TestCase):
    def test_example_passes(self):
        example = Path(__file__).resolve().parent.parent / "examples" / "constraint-adr"
        res = check_constraints.check_constraints(example)
        self.assertEqual(res["failures"], [], msg=str(res["failures"]))
        self.assertEqual(res["checked"], 1)  # the deterministic Pact gate
        self.assertTrue(any(enf == "advisory" for _, _, enf in res["advisories"]))


if __name__ == "__main__":
    unittest.main()
