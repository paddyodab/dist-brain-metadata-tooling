#!/usr/bin/env python3
"""Tests for brain_store (stdlib only): python3 engine/test_brain_store.py"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from brain_store import BrainStore


SAMPLE_NODES = [
    {
        "id": "flag:enable_custom_aliases",
        "type": "flag",
        "title": "enable_custom_aliases",
        "intent": "Allow callers to choose their own short code.",
        "subsystem": "flags",
        "facts": {"default": False, "owner": "growth"},
        "provenance": {"source_path": "flags.yml", "source_sha": "aaa", "status": "verified"},
    },
    {
        "id": "src/linkshort/shorten.py#create_short_link",
        "type": "function",
        "title": "create_short_link",
        "intent": "A URL gets a short code; custom alias path uses a feature flag.",
        "subsystem": "python:shorten",
        "facts": {"params": ["store", "url"], "returns": "ShortLink", "raises": ["InvalidURL"],
                  "feature": "custom-aliases", "flag": "enable_custom_aliases"},
        "provenance": {"source_path": "src/linkshort/shorten.py", "source_sha": "bbb", "status": "verified"},
    },
]
SAMPLE_EDGES = [
    {"from": "src/linkshort/shorten.py#create_short_link", "to": "flag:enable_custom_aliases",
     "type": "gated-by", "origin": "authored"},
]


class BrainStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        self.tmp.close()
        self.path = Path(self.tmp.name)
        self.store = BrainStore.open(self.path)

    def tearDown(self) -> None:
        self.store.close()
        self.path.unlink(missing_ok=True)

    def test_upsert_and_load(self) -> None:
        self.store.upsert_main("sha1", SAMPLE_NODES, SAMPLE_EDGES,
                               {"added": SAMPLE_NODES, "removed": [], "changed": []})
        graph = self.store.load_graph("main")
        self.assertEqual(graph["generated_from_sha"], "sha1")
        self.assertEqual(len(graph["nodes"]), 2)
        self.assertEqual(len(graph["edges"]), 1)

    def test_incremental_upsert(self) -> None:
        self.store.upsert_main("sha1", SAMPLE_NODES, SAMPLE_EDGES,
                               {"added": SAMPLE_NODES, "removed": [], "changed": []})
        updated = [dict(SAMPLE_NODES[1])]
        updated[0]["intent"] = "Updated intent for custom aliases."
        updated[0]["provenance"] = dict(SAMPLE_NODES[1]["provenance"])
        updated[0]["provenance"]["source_sha"] = "ccc"
        nodes = [SAMPLE_NODES[0], updated[0]]
        self.store.upsert_main("sha2", nodes, SAMPLE_EDGES, {
            "added": [], "removed": [], "changed": updated,
        })
        graph = self.store.load_graph("main")
        fn = next(n for n in graph["nodes"] if n["id"].endswith("create_short_link"))
        self.assertIn("Updated intent", fn["intent"])
        self.assertEqual(fn["first_seen_sha"], "sha1")
        self.assertEqual(fn["last_touched_sha"], "sha2")

    def test_search_multi_word(self) -> None:
        self.store.upsert_main("sha1", SAMPLE_NODES, SAMPLE_EDGES,
                               {"added": SAMPLE_NODES, "removed": [], "changed": []})
        hits = self.store.search("custom aliases")
        ids = {h["id"] for h in hits}
        self.assertIn("flag:enable_custom_aliases", ids)
        self.assertIn("src/linkshort/shorten.py#create_short_link", ids)

    def test_snapshot_revision(self) -> None:
        self.store.upsert_main("sha1", SAMPLE_NODES, SAMPLE_EDGES,
                               {"added": SAMPLE_NODES, "removed": [], "changed": []})
        self.store.snapshot_revision("v1.0", "sha1")
        tag = self.store.load_graph("v1.0")
        self.assertEqual(len(tag["nodes"]), 2)
        main = self.store.load_graph("main")
        main["nodes"][1]["intent"] = "changed on main"
        self.store.upsert_main("sha2", main["nodes"], main["edges"], {
            "added": [], "removed": [], "changed": [main["nodes"][1]],
        })
        tag2 = self.store.load_graph("v1.0")
        self.assertIn("short code", tag2["nodes"][0]["intent"] or "")

    def test_render_features_md(self) -> None:
        self.store.upsert_main("sha1", SAMPLE_NODES, SAMPLE_EDGES,
                               {"added": SAMPLE_NODES, "removed": [], "changed": []})
        md = self.store.render_features_md("main")
        self.assertIn("# Features", md)
        self.assertIn("enable_custom_aliases", md)
        self.assertIn("brain.sqlite", md)


if __name__ == "__main__":
    unittest.main()