"""Unit tests for brain_query (stdlib only — run: python3 -m unittest mcp/test_brain_query.py)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from brain_query import Brain, merge_graphs, parse_sources


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


class JoinTests(unittest.TestCase):
    def test_parse_comma_separated_sources(self) -> None:
        spec = "my-app|https://example.com/wiki/my-app/graph.json,lib|/tmp/lib.json"
        parsed = parse_sources(spec)
        self.assertEqual(parsed[0][0], "my-app")
        self.assertEqual(parsed[1][0], "lib")

    def test_merge_prefixes_ids(self) -> None:
        g1 = {"nodes": [{"id": "src/a.py#fn", "type": "function", "title": "fn"}],
              "edges": [{"from": "src/a.py#fn", "to": "flag:x", "type": "gated-by"}],
              "generated_from_sha": "aaa"}
        g2 = {"nodes": [{"id": "flag:y", "type": "flag", "title": "y"}],
              "edges": [], "generated_from_sha": "bbb"}
        merged = merge_graphs([("app", g1), ("lib", g2)])
        self.assertTrue(merged["joined"])
        ids = {n["id"] for n in merged["nodes"]}
        self.assertIn("app:src/a.py#fn", ids)
        self.assertIn("lib:flag:y", ids)
        self.assertEqual(merged["edges"][0]["from"], "app:src/a.py#fn")
        self.assertEqual(len(merged["sources"]), 2)

    def test_search_scoped_by_source(self) -> None:
        graph = merge_graphs([
            ("app", {"nodes": [{"id": "src/a.py#resolve", "type": "function",
                                "title": "resolve", "intent": "resolve urls"}], "edges": []}),
            ("lib", {"nodes": [{"id": "src/b.py#parse", "type": "function",
                                "title": "parse", "intent": "parse urls"}], "edges": []}),
        ])
        brain = Brain("unused")
        brain._graph = graph
        app_hits = brain.search("resolve", source="app")
        self.assertEqual(len(app_hits), 1)
        self.assertEqual(app_hits[0]["source"], "app")
        self.assertEqual(brain.search("resolve", source="lib"), [])


class SqliteBrainTests(unittest.TestCase):
    def test_sqlite_overview_and_search(self) -> None:
        db = "/tmp/my-app-brain/brain.sqlite"
        if not Path(db).exists():
            self.skipTest("run materialize first")
        brain = Brain(db, revision="main").load()
        ov = brain.overview()
        self.assertEqual(ov["storage"], "sqlite")
        self.assertIn("enable_custom_aliases", ov["flags"])
        hits = brain.search("custom aliases")
        ids = {h["id"] for h in hits}
        self.assertTrue(ids)


if __name__ == "__main__":
    unittest.main()