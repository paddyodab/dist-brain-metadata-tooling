#!/usr/bin/env python3
"""Tests for house rules: yml parsing + the rung-3 gate runner.
Run: python3 engine/test_check_constraints.py

Discriminating specs:
  * A bare record ADR (no frontmatter) keeps its historic node shape (id/title/intent/
    status, kind='record').
  * house-rules/*.yml are machine-readable constraints: only accepted rules are enforced.
  * A deterministic gate that exits nonzero — or is missing, or absent on a deterministic
    rule — fails the build (fail-closed).
  * advisory/semantic are reported, never a failure.
"""
from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

import check_constraints
from extract import adr_nodes, house_rules_nodes, _parse_house_rule


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

# A deterministic rule whose gate just echoes its own exit code from a file.
GATE_TPL = """\
import os, sys
from pathlib import Path
root = Path(os.environ.get("GITHUB_WORKSPACE") or ".")
sys.exit(int((root / "gate_rc.txt").read_text().strip()))
"""


def _rule(title, *, status="accepted", enforcement="advisory", gate=None,
          applies_to=None, rule_id=None) -> str:
    lines = [f"rule: {title}", f"status: {status}", f"enforcement: {enforcement}"]
    if rule_id:
        lines.insert(0, f"id: {rule_id}")
    if gate:
        lines.append(f"gate: {gate}")
    if applies_to:
        lines.append(f"applies_to: {applies_to}")
    lines.append("rationale: |")
    lines.append("  The rule body.")
    return "\n".join(lines) + "\n"


class HouseRuleParserTests(unittest.TestCase):
    def test_empty_returns_none(self):
        self.assertIsNone(_parse_house_rule(""))

    def test_block_scalar_rationale(self):
        parsed = _parse_house_rule("""\
            id: 1
            rule: Use Pact
            rationale: |
              Every boundary must have a contract.
            status: accepted
            enforcement: deterministic
            gate: checks/g.py
            applies_to: services/
            """)
        self.assertEqual(parsed["rule"], "Use Pact")
        self.assertEqual(parsed["rationale"], "Every boundary must have a contract.")
        self.assertEqual(parsed["gate"], "checks/g.py")
        self.assertEqual(parsed["applies_to"], "services/")

    def test_inline_rationale(self):
        parsed = _parse_house_rule("rule: Mono\nrationale: one repo\nstatus: accepted")
        self.assertEqual(parsed["rationale"], "one repo")


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
            self.assertEqual(node["facts"]["kind"], "record")
            self.assertNotIn("enforcement", node["facts"])

    def test_record_adr_with_frontmatter_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            # old constraint frontmatter now lives in house-rules, not decisions
            _write(root, "decisions/0007-pact.md", """\
                ---
                id: 0007
                title: Use Pact
                status: accepted
                ---
                # Use Pact

                ## Decision

                The record body.
                """)
            (node,) = adr_nodes(root)
            self.assertEqual(node["facts"]["kind"], "record")
            self.assertNotIn("enforcement", node["facts"])
            self.assertEqual(node["title"], "Use Pact")
            self.assertEqual(node["intent"], "The record body.")


class GateRunnerTests(unittest.TestCase):
    def _root_with_gate(self, d, rc: int, **kw) -> Path:
        root = Path(d)
        _write(root, "house-rules/pact.yml",
               _rule("Use Pact", enforcement="deterministic", gate="checks/g.py", **kw))
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
            self.assertEqual(res["failures"][0][0], "house-rule:pact")

    def test_missing_gate_script_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _write(root, "house-rules/pact.yml",
                   _rule("Use Pact", enforcement="deterministic", gate="checks/nope.py"))
            res = check_constraints.check_constraints(root)
            self.assertEqual(len(res["failures"]), 1)
            self.assertIn("not found", res["failures"][0][2])

    def test_deterministic_without_gate_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _write(root, "house-rules/pact.yml", _rule("Use Pact", enforcement="deterministic"))
            res = check_constraints.check_constraints(root)
            self.assertEqual(len(res["failures"]), 1)
            self.assertIn("no gate", res["failures"][0][2])

    def test_proposed_rule_is_inert(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._root_with_gate(d, 1)  # gate would fail if run
            p = root / "house-rules/pact.yml"
            p.write_text(p.read_text().replace("status: accepted", "status: proposed"))
            res = check_constraints.check_constraints(root)
            self.assertEqual(res, {"failures": [], "advisories": [], "checked": 0, "total": 0})

    def test_advisory_and_semantic_are_reported_not_failed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _write(root, "house-rules/mono.yml", _rule("Monorepo", enforcement="advisory"))
            _write(root, "house-rules/comp.yml", _rule("Composition", enforcement="semantic"))
            res = check_constraints.check_constraints(root)
            self.assertEqual(res["failures"], [])
            self.assertEqual(res["checked"], 0)
            kinds = sorted(enf for _, _, enf in res["advisories"])
            self.assertEqual(kinds, ["advisory", "semantic"])

    def test_record_adr_is_not_a_rule(self):
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
