"""Unit tests for brain_query (stdlib only — run: python3 -m unittest mcp/test_brain_query.py)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from brain_query import Brain


class SearchTests(unittest.TestCase):
    def setUp(self) -> None:
        graph = {
            "nodes": [
                {
                    "id": "flag:enable_custom_aliases",
                    "type": "flag",
                    "title": "enable_custom_aliases",
                    "intent": "Allow callers to choose their own short code (paid feature).",
                },
                {
                    "id": "src/linkshort/shorten.py#create_short_link",
                    "type": "function",
                    "title": "create_short_link",
                    "intent": (
                        "A URL gets a deterministic short code. A caller may request "
                        "a custom alias; that path is guarded by a feature flag."
                    ),
                    "subsystem": "python:shorten",
                },
                {
                    "id": "src/linkshort/resolve.py#resolve",
                    "type": "function",
                    "title": "resolve",
                    "intent": "Look up a short code and return the destination URL.",
                    "subsystem": "python:resolve",
                },
            ],
            "edges": [],
        }
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump(graph, tmp)
        tmp.close()
        self.brain = Brain(tmp.name).load()
        self._tmp_path = Path(tmp.name)

    def tearDown(self) -> None:
        self._tmp_path.unlink(missing_ok=True)

    def test_single_token_substring(self) -> None:
        hits = self.brain.search("alias")
        ids = {h["id"] for h in hits}
        self.assertIn("flag:enable_custom_aliases", ids)
        self.assertIn("src/linkshort/shorten.py#create_short_link", ids)

    def test_multi_word_and_match(self) -> None:
        hits = self.brain.search("custom aliases")
        ids = {h["id"] for h in hits}
        self.assertIn("flag:enable_custom_aliases", ids)
        self.assertIn("src/linkshort/shorten.py#create_short_link", ids)
        self.assertNotIn("src/linkshort/resolve.py#resolve", ids)

    def test_multi_word_no_match_when_token_missing(self) -> None:
        self.assertEqual(self.brain.search("custom analytics"), [])

    def test_empty_query(self) -> None:
        self.assertEqual(self.brain.search("   "), [])


if __name__ == "__main__":
    unittest.main()