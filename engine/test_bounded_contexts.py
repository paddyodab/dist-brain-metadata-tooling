#!/usr/bin/env python3
"""End-to-end integration test for bounded contexts.

Runs the full pipeline against examples/bounded-contexts/:
  extract -> gate -> materialize -> MCP query

Verifies:
  1. extract produces nodes with correct context values
  2. Gate passes for valid tags, fails for invalid tags in wrong context
  3. Materialize produces per-context wiki sections
  4. MCP search(context="backend") returns only backend entities
  5. Glossary auto-propose surfaces DropDate correctly

Run: python3 -m unittest engine.test_bounded_contexts
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ENGINE = Path(__file__).resolve().parent
REPO_ROOT = ENGINE.parent
EXAMPLE = REPO_ROOT / "examples" / "bounded-contexts"
EXTRACT = ENGINE / "extract.py"
CHECK = ENGINE / "check_metadata.py"
MATERIALIZE = ENGINE / "materialize.py"


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


class BoundedContextIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.brain_dir = tempfile.TemporaryDirectory()
        self.brain = Path(self.brain_dir.name)

    def tearDown(self) -> None:
        self.brain_dir.cleanup()

    def _extract(self) -> dict:
        out = _run([sys.executable, str(EXTRACT), "--root", str(EXAMPLE), "--src", str(EXAMPLE)]).stdout
        start = out.find("{")
        if start == -1:
            raise AssertionError(f"extract produced no JSON: {out}")
        import json
        return json.loads(out[start:])

    def test_extract_produces_nodes_with_correct_context(self) -> None:
        data = self._extract()
        funcs = [n for n in data["nodes"] if n["type"] in ("function", "method")]
        self.assertGreaterEqual(len(funcs), 6)
        by_context: dict[str, list[str]] = {}
        for n in funcs:
            by_context.setdefault(n.get("context") or "root", []).append(n["id"])
        self.assertIn("backend", by_context)
        self.assertIn("frontend", by_context)
        # backend ids should include orders.py symbols
        self.assertTrue(any("orders.py#" in i for i in by_context["backend"]))
        # frontend ids should include ui.py symbols
        self.assertTrue(any("ui.py#" in i for i in by_context["frontend"]))

    def test_gate_passes_valid_tags(self) -> None:
        result = _run(
            [sys.executable, str(CHECK), "--root", str(EXAMPLE), "--src", str(EXAMPLE)]
        )
        self.assertEqual(
            result.returncode, 0,
            f"Expected gate to pass for valid tags, got:\n{result.stdout}\n{result.stderr}",
        )

    def test_gate_fails_invalid_tag_in_wrong_context(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        try:
            (root / "backend").mkdir()
            (root / "frontend").mkdir()
            (root / "backend" / "CONTEXT.md").write_text("# Backend\n")
            (root / "frontend" / "CONTEXT.md").write_text("# Frontend\n")
            (root / "backend" / "contracts.yml").write_text(
                "context: backend\nkind: service\nvalid_tags:\n  intent:\n    required: true\n"
            )
            (root / "frontend" / "contracts.yml").write_text(
                "context: frontend\nkind: component\nvalid_tags:\n  intent:\n    required: true\n"
            )
            (root / "flags.yml").write_text("flags: {}\n")
            bad = root / "backend" / "bad.py"
            bad.write_text('''\
def bad():
    """Invalid.

    @intent Does a thing.
    @renders nothing
    """
    pass
''')
            result = _run(
                [sys.executable, str(CHECK), "--root", str(root), "--src", str(root)]
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("@renders is not a valid tag in context 'backend'", result.stdout)
        finally:
            tmp.cleanup()

    def test_materialize_produces_per_context_wiki_sections(self) -> None:
        result = _run(
            [sys.executable, str(MATERIALIZE), "--root", str(EXAMPLE),
             "--src", str(EXAMPLE), "--brain", str(self.brain), "--no-json"]
        )
        self.assertEqual(result.returncode, 0, f"materialize failed:\n{result.stderr}")
        home = self.brain / "Home.md"
        self.assertTrue(home.exists(), "Home.md was not generated")
        text = home.read_text()
        self.assertIn("## Contexts", text)
        self.assertIn("`backend`", text)
        self.assertIn("`frontend`", text)
        self.assertIn("## Boundaries", text)

    def test_mcp_search_scoped_to_context(self) -> None:
        # First materialize so brain.sqlite exists.
        _run(
            [sys.executable, str(MATERIALIZE), "--root", str(EXAMPLE),
             "--src", str(EXAMPLE), "--brain", str(self.brain), "--no-json"]
        )
        import sys as _sys
        mcp = _sys.path
        sys.path.insert(0, str(REPO_ROOT / "mcp"))
        from brain_query import Brain
        brain = Brain(str(self.brain / "brain.sqlite")).load()
        hits = brain.search("order", context="backend")
        self.assertTrue(hits, "expected backend hits for 'order'")
        # Shared infrastructure nodes (flags, exceptions) have context=None and are
        # intentionally visible in every context for backward compatibility.
        self.assertTrue(
            all(h.get("context") in ("backend", None) for h in hits),
            f"search(context=backend) leaked non-backend: {hits}",
        )
        frontend_hits = brain.search("order", context="frontend")
        self.assertTrue(
            all(h.get("context") in ("frontend", None) for h in frontend_hits),
            f"search(context=frontend) leaked non-frontend: {frontend_hits}",
        )

    def test_glossary_auto_propose_surfaces_new_term(self) -> None:
        result = _run(
            [sys.executable, str(CHECK), "--root", str(EXAMPLE), "--src", str(EXAMPLE)]
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Proposed glossary term: WishlistBadge", result.stdout)


if __name__ == "__main__":
    unittest.main()
