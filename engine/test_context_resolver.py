#!/usr/bin/env python3
"""Tests for context_resolver (stdlib only): python3 engine/test_context_resolver.py"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from context_resolver import resolve_context, context_dir, contracts_path, glossary_path


class ContextResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_map(self, body: str) -> None:
        (self.root / "CONTEXT-MAP.md").write_text(body)

    def test_no_context_file_returns_none(self) -> None:
        """A repo with no CONTEXT.md resolves to None (today's behavior)."""
        f = self.root / "src" / "services" / "thing.py"
        f.parent.mkdir(parents=True)
        f.write_text("def foo(): pass\n")
        self.assertIsNone(resolve_context(f, self.root))

    def test_root_context_returns_root(self) -> None:
        """A CONTEXT.md at root resolves to 'root'."""
        (self.root / "CONTEXT.md").write_text("# Root context\n")
        f = self.root / "src" / "services" / "thing.py"
        f.parent.mkdir(parents=True)
        f.write_text("def foo(): pass\n")
        self.assertEqual(resolve_context(f, self.root), "root")

    def test_backend_context(self) -> None:
        """A file under backend/ resolves to 'backend' when backend/CONTEXT.md exists."""
        backend = self.root / "backend"
        backend.mkdir()
        (backend / "CONTEXT.md").write_text("# Backend\n")
        f = backend / "services" / "thing.py"
        f.parent.mkdir(parents=True)
        f.write_text("def foo(): pass\n")
        self.assertEqual(resolve_context(f, self.root), "backend")

    def test_walks_up_to_nearest_context(self) -> None:
        """A file in backend/src/services/ resolves to 'backend', not 'services'."""
        backend = self.root / "backend"
        services = backend / "src" / "services"
        backend.mkdir()
        (backend / "CONTEXT.md").write_text("# Backend\n")
        # Intentionally create a nested directory without its own CONTEXT.md.
        f = services / "thing.py"
        f.parent.mkdir(parents=True)
        f.write_text("def foo(): pass\n")
        self.assertEqual(resolve_context(f, self.root), "backend")

    def test_deepest_context_wins(self) -> None:
        """A nested CONTEXT.md overrides the parent one."""
        backend = self.root / "backend"
        services = backend / "src" / "services"
        backend.mkdir()
        (backend / "CONTEXT.md").write_text("# Backend\n")
        services.mkdir(parents=True)
        (services / "CONTEXT.md").write_text("# Services\n")
        f = services / "thing.py"
        f.write_text("def foo(): pass\n")
        self.assertEqual(resolve_context(f, self.root), "backend/src/services")

    def test_path_outside_root_returns_none(self) -> None:
        """A file outside root resolves to None."""
        other = Path(self.tmp.name).parent / "outside_root.py"
        other.write_text("def foo(): pass\n")
        self.assertIsNone(resolve_context(other, self.root))

    def test_context_dir_root(self) -> None:
        self.assertEqual(context_dir(self.root, None), self.root.resolve())
        self.assertEqual(context_dir(self.root, "root"), self.root.resolve())

    def test_context_dir_named(self) -> None:
        self.assertEqual(context_dir(self.root, "backend"), self.root.resolve() / "backend")

    def test_contracts_path(self) -> None:
        self.assertEqual(
            contracts_path(self.root, "backend"),
            self.root.resolve() / "backend" / "contracts.yml",
        )
        self.assertEqual(contracts_path(self.root, None), self.root.resolve() / "contracts.yml")

    def test_glossary_path(self) -> None:
        self.assertEqual(
            glossary_path(self.root, "backend"),
            self.root.resolve() / "backend" / "CONTEXT.md",
        )
        self.assertEqual(glossary_path(self.root, None), self.root.resolve() / "CONTEXT.md")

    def test_context_map_overrides_walk_up(self) -> None:
        """CONTEXT-MAP.md is authoritative even without a nearby CONTEXT.md."""
        self._write_map(
            """# Context Map

| Context  | Location  | Kind      | Description |
|----------|-----------|-----------|-------------|
| backend  | backend/  | service   | API server  |
| frontend | frontend/ | component | SPA         |
"""
        )
        f = self.root / "backend" / "src" / "thing.py"
        f.parent.mkdir(parents=True)
        f.write_text("def foo(): pass\n")
        self.assertEqual(resolve_context(f, self.root), "backend")

    def test_context_map_falls_back_when_file_outside_map(self) -> None:
        """Files not in the map still use walk-up fallback."""
        self._write_map(
            """# Context Map

| Context  | Location  | Kind      | Description |
|----------|-----------|-----------|-------------|
| backend  | backend/  | service   | API server  |
"""
        )
        shared = self.root / "shared" / "utils.py"
        shared.parent.mkdir(parents=True)
        (shared.parent / "CONTEXT.md").write_text("# Shared\n")
        shared.write_text("def util(): pass\n")
        self.assertEqual(resolve_context(shared, self.root), "shared")

    def test_context_map_longest_prefix_wins(self) -> None:
        """A more specific mapped location wins over a shorter one."""
        self._write_map(
            """# Context Map

| Context   | Location          | Kind     | Description |
|-----------|-------------------|----------|-------------|
| backend   | backend/          | service  | API         |
| billing   | backend/billing/  | service  | Billing     |
"""
        )
        f = self.root / "backend" / "billing" / "invoice.py"
        f.parent.mkdir(parents=True)
        f.write_text("def inv(): pass\n")
        self.assertEqual(resolve_context(f, self.root), "billing")

    def test_context_map_root_location(self) -> None:
        """A map row with Location '.' or 'root/' resolves root files to 'root'."""
        self._write_map(
            """# Context Map

| Context  | Location | Kind     | Description |
|----------|----------|----------|-------------|
| root     | .        | root     | Shared      |
| backend  | backend/ | service  | API         |
"""
        )
        f = self.root / "tooling.py"
        f.write_text("def tool(): pass\n")
        self.assertEqual(resolve_context(f, self.root), "root")

    def test_context_map_ignores_non_context_table(self) -> None:
        """A Markdown table without Context/Location columns is ignored."""
        self._write_map(
            """# Some other table

| Name | Value |
|------|-------|
| foo  | bar   |

| Context  | Location  | Kind      | Description |
|----------|-----------|-----------|-------------|
| backend  | backend/  | service   | API server  |
"""
        )
        backend = self.root / "backend"
        backend.mkdir()
        (backend / "CONTEXT.md").write_text("# Backend\n")
        f = backend / "thing.py"
        f.write_text("def foo(): pass\n")
        # First table has no Context/Location, so it is ignored; second table wins.
        self.assertEqual(resolve_context(f, self.root), "backend")


if __name__ == "__main__":
    unittest.main()
