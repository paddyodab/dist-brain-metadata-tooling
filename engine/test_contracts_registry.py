#!/usr/bin/env python3
"""Tests for contracts_registry (stdlib only): python3 engine/test_contracts_registry.py"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from contracts_registry import load_contracts


BACKEND_YML = """\
context: backend
kind: service
valid_tags:
  intent:
    required: true
    description: "What this function guarantees and why it exists"
  feature:
    required: false
    description: "Feature flag controlling this function"
  param:
    required: auto
    description: "Parameter name and type"
  returns:
    required: auto
    description: "Return type and shape"
  raises:
    required: false
    description: "Exceptions this function can raise"
  schema:
    required: false
    description: "DB schema or Pydantic model this function reads/writes"
glossary_file: CONTEXT.md
"""

FRONTEND_YML = """\
context: frontend
kind: component
valid_tags:
  intent:
    required: true
  props:
    required: auto
  renders:
    required: true
  state:
    required: false
"""


class ContractsRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_missing_file_returns_empty(self) -> None:
        """When no contracts.yml exists, load_contracts returns {}."""
        self.assertEqual(load_contracts(self.root / "contracts.yml"), {})

    def test_parses_backend_valid_tags(self) -> None:
        path = self.root / "contracts.yml"
        path.write_text(BACKEND_YML)
        contracts = load_contracts(path)
        self.assertEqual(set(contracts), {"intent", "feature", "param", "returns", "raises", "schema"})
        self.assertEqual(contracts["intent"], {"required": "true", "description": "What this function guarantees and why it exists"})
        self.assertEqual(contracts["param"], {"required": "auto", "description": "Parameter name and type"})
        self.assertEqual(contracts["feature"], {"required": "false", "description": "Feature flag controlling this function"})

    def test_parses_frontend_valid_tags(self) -> None:
        path = self.root / "frontend" / "contracts.yml"
        path.parent.mkdir()
        path.write_text(FRONTEND_YML)
        contracts = load_contracts(path)
        self.assertEqual(set(contracts), {"intent", "props", "renders", "state"})
        self.assertEqual(contracts["intent"], {"required": "true"})
        self.assertEqual(contracts["props"], {"required": "auto"})
        self.assertEqual(contracts["renders"], {"required": "true"})
        self.assertEqual(contracts["state"], {"required": "false"})

    def test_ignores_comments_and_blank_lines(self) -> None:
        text = """\
# top comment
valid_tags:
  # inline comment
  intent:
    required: true
    description: "What this function guarantees"

  param:
    required: auto
"""
        path = self.root / "contracts.yml"
        path.write_text(text)
        contracts = load_contracts(path)
        self.assertEqual(contracts["intent"], {"required": "true", "description": "What this function guarantees"})
        self.assertEqual(contracts["param"], {"required": "auto"})

    def test_bogus_top_level_does_not_pollute_tags(self) -> None:
        """Keys outside valid_tags are ignored."""
        text = """\
context: backend
kind: service
not_tags:
  something:
    required: true
valid_tags:
  intent:
    required: true
"""
        path = self.root / "contracts.yml"
        path.write_text(text)
        contracts = load_contracts(path)
        self.assertEqual(set(contracts), {"intent"})


if __name__ == "__main__":
    unittest.main()
