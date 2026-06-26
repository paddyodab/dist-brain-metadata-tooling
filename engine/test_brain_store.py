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

    def test_context_persists(self) -> None:
        """Node with context="backend" persists and loads back."""
        nodes = [dict(SAMPLE_NODES[0], context="backend"),
                 dict(SAMPLE_NODES[1], context="backend")]
        self.store.upsert_main("sha1", nodes, SAMPLE_EDGES,
                               {"added": nodes, "removed": [], "changed": []})
        graph = self.store.load_graph("main")
        for n in graph["nodes"]:
            self.assertEqual(n["context"], "backend")

    def test_context_defaults_null(self) -> None:
        """Nodes without context key get NULL (today's behavior)."""
        self.store.upsert_main("sha1", SAMPLE_NODES, SAMPLE_EDGES,
                               {"added": SAMPLE_NODES, "removed": [], "changed": []})
        graph = self.store.load_graph("main")
        for n in graph["nodes"]:
            self.assertIsNone(n["context"])

    def test_search_context_none_returns_all(self) -> None:
        """search(context=None) returns all nodes (backward compat)."""
        nodes = [dict(SAMPLE_NODES[0], context="backend"),
                 dict(SAMPLE_NODES[1], context="frontend")]
        self.store.upsert_main("sha1", nodes, SAMPLE_EDGES,
                               {"added": nodes, "removed": [], "changed": []})
        hits = self.store.search("custom")
        ids = {h["id"] for h in hits}
        self.assertIn("flag:enable_custom_aliases", ids)
        self.assertIn("src/linkshort/shorten.py#create_short_link", ids)

    def test_search_context_scoped(self) -> None:
        """search(context='backend') returns only backend + NULL-context nodes."""
        nodes = [dict(SAMPLE_NODES[0], context="backend"),
                 dict(SAMPLE_NODES[1], context="frontend")]
        self.store.upsert_main("sha1", nodes, SAMPLE_EDGES,
                               {"added": nodes, "removed": [], "changed": []})
        hits = self.store.search("custom", context="backend")
        ids = {h["id"] for h in hits}
        self.assertIn("flag:enable_custom_aliases", ids)
        self.assertNotIn("src/linkshort/shorten.py#create_short_link", ids)

    def test_search_context_includes_null(self) -> None:
        """search(context='backend') includes NULL-context nodes (root visible everywhere)."""
        nodes = [dict(SAMPLE_NODES[0]),  # no context = NULL
                 dict(SAMPLE_NODES[1], context="backend")]
        self.store.upsert_main("sha1", nodes, SAMPLE_EDGES,
                               {"added": nodes, "removed": [], "changed": []})
        hits = self.store.search("custom", context="backend")
        ids = {h["id"] for h in hits}
        # NULL-context node is visible in backend search
        self.assertIn("flag:enable_custom_aliases", ids)
        self.assertIn("src/linkshort/shorten.py#create_short_link", ids)

    def test_search_context_excludes_other(self) -> None:
        """search(context='backend') does not return frontend-only nodes."""
        nodes = [dict(SAMPLE_NODES[0], context="frontend"),
                 dict(SAMPLE_NODES[1], context="backend")]
        self.store.upsert_main("sha1", nodes, SAMPLE_EDGES,
                               {"added": nodes, "removed": [], "changed": []})
        hits = self.store.search("aliases", context="backend")
        ids = {h["id"] for h in hits}
        self.assertNotIn("flag:enable_custom_aliases", ids)
        self.assertIn("src/linkshort/shorten.py#create_short_link", ids)

    def test_v1_to_v2_migration(self) -> None:
        """A v1 brain (no context column) migrates automatically on open."""
        # Use a fresh path (setUp already created a v2 store at self.path)
        tmp2 = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        tmp2.close()
        v1_path = Path(tmp2.name)
        try:
            # Manually create a v1-style brain (no context column)
            import sqlite3 as sq
            conn = sq.connect(str(v1_path))
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS revisions (
                  ref TEXT PRIMARY KEY, sha TEXT NOT NULL,
                  node_count INTEGER NOT NULL DEFAULT 0,
                  edge_count INTEGER NOT NULL DEFAULT 0,
                  materialized_at TEXT NOT NULL,
                  is_rolling INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS nodes (
                  revision_ref TEXT NOT NULL, id TEXT NOT NULL, type TEXT NOT NULL,
                  title TEXT, intent TEXT, subsystem TEXT,
                  facts_json TEXT NOT NULL DEFAULT '{}',
                  provenance_json TEXT NOT NULL DEFAULT '{}',
                  source_path TEXT, source_sha TEXT,
                  provenance_status TEXT NOT NULL DEFAULT 'verified',
                  first_seen_sha TEXT, last_touched_sha TEXT,
                  PRIMARY KEY (revision_ref, id)
                );
                CREATE TABLE IF NOT EXISTS edges (
                  revision_ref TEXT NOT NULL, from_id TEXT NOT NULL, to_id TEXT NOT NULL,
                  edge_type TEXT NOT NULL, origin TEXT,
                  PRIMARY KEY (revision_ref, from_id, to_id, edge_type)
                );
                CREATE TABLE IF NOT EXISTS intent_history (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  revision_ref TEXT NOT NULL, entity_id TEXT NOT NULL,
                  sha TEXT NOT NULL, intent TEXT NOT NULL, recorded_at TEXT NOT NULL
                );
                INSERT INTO meta(key, value) VALUES('schema_version', '1');
            """)
            conn.execute(
                "INSERT INTO nodes(revision_ref, id, type, title, intent, subsystem, "
                "facts_json, provenance_json, source_path, source_sha, provenance_status) "
                "VALUES ('main', 'test:node', 'function', 'test_node', 'test intent', 'test', "
                "'{}', '{}', 'test.py', 'sha1', 'verified')"
            )
            conn.execute(
                "INSERT INTO revisions(ref, sha, node_count, edge_count, materialized_at, is_rolling) "
                "VALUES ('main', 'sha1', 1, 0, '2026-01-01T00:00:00+00:00', 1)"
            )
            conn.commit()
            conn.close()

            # Open — should auto-migrate (ALTER TABLE add context column)
            store = BrainStore.open(v1_path)
            graph = store.load_graph("main")
            self.assertEqual(len(graph["nodes"]), 1)
            self.assertIsNone(graph["nodes"][0]["context"])  # migrated row has NULL context

            # Verify the column exists now
            cols = store.conn.execute("PRAGMA table_info(nodes)").fetchall()
            self.assertTrue(any(c["name"] == "context" for c in cols))

            # Verify we can upsert with context after migration
            nodes = [dict(SAMPLE_NODES[0], context="backend")]
            store.upsert_main("sha2", nodes, [],
                             {"added": nodes, "removed": [{"id": "test:node"}], "changed": []})
            graph = store.load_graph("main")
            fn = next(n for n in graph["nodes"] if n["id"] == "flag:enable_custom_aliases")
            self.assertEqual(fn["context"], "backend")
            store.close()
        finally:
            v1_path.unlink(missing_ok=True)

    def test_snapshot_preserves_context(self) -> None:
        """snapshot_revision copies the context column to the tag revision."""
        nodes = [dict(SAMPLE_NODES[0], context="backend"),
                 dict(SAMPLE_NODES[1], context="frontend")]
        self.store.upsert_main("sha1", nodes, SAMPLE_EDGES,
                               {"added": nodes, "removed": [], "changed": []})
        self.store.snapshot_revision("v1.0", "sha1")
        tag = self.store.load_graph("v1.0")
        contexts = {n["id"]: n["context"] for n in tag["nodes"]}
        self.assertEqual(contexts["flag:enable_custom_aliases"], "backend")
        self.assertEqual(contexts["src/linkshort/shorten.py#create_short_link"], "frontend")


if __name__ == "__main__":
    unittest.main()