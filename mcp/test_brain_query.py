"""Unit tests for brain_query (stdlib only — run: python3 -m unittest mcp/test_brain_query.py)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from brain_query import Brain, merge_graphs, parse_sources
from brain_store import BrainStore  # brain_query puts engine/ on sys.path at import


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


class DecisionsKindTests(unittest.TestCase):
    """list_decisions surfaces kind/enforcement and can filter to the house rules."""

    def setUp(self) -> None:
        graph = {
            "nodes": [
                {"id": "decision:0001-record", "type": "decision", "title": "A record",
                 "intent": "retrospective", "facts": {"status": "Accepted", "kind": "record"}},
                {"id": "decision:0007-pact", "type": "decision", "title": "Use Pact",
                 "intent": "premise", "facts": {"status": "accepted", "kind": "constraint",
                 "enforcement": "deterministic", "applies_to": "boundaries"}},
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

    def test_all_decisions_carry_kind(self) -> None:
        kinds = {d["id"]: d["kind"] for d in self.brain.decisions()}
        self.assertEqual(kinds["decision:0001-record"], "record")
        self.assertEqual(kinds["decision:0007-pact"], "constraint")

    def test_filter_to_constraints(self) -> None:
        rules = self.brain.decisions(kind="constraint")
        self.assertEqual([d["id"] for d in rules], ["decision:0007-pact"])
        self.assertEqual(rules[0]["enforcement"], "deterministic")
        self.assertEqual(rules[0]["applies_to"], "boundaries")

    def test_overview_reports_kind(self) -> None:
        kinds = {d["id"]: d["kind"] for d in self.brain.overview()["decisions"]}
        self.assertEqual(kinds["decision:0001-record"], "record")
        self.assertEqual(kinds["decision:0007-pact"], "constraint")


class HistoryWhyTests(unittest.TestCase):
    """history()/why() over a real sqlite brain with an intent change across two revisions."""

    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        self.tmp.close()
        self.path = Path(self.tmp.name)
        store = BrainStore.open(self.path)
        alpha0 = {"id": "src/m.py#alpha", "type": "function", "title": "alpha",
                  "intent": "Alpha returns x.", "subsystem": "python:m",
                  "facts": {"params": ["x"], "returns": "int", "raises": [], "flag": "f"},
                  "provenance": {"source_path": "src/m.py", "source_sha": "aaa",
                                 "status": "inferred"}}
        flag = {"id": "flag:f", "type": "flag", "title": "f", "intent": "toggle",
                "subsystem": "flags", "facts": {},
                "provenance": {"source_path": "flags.yml", "source_sha": "f1",
                               "status": "verified"}}
        edges = [{"from": "src/m.py#alpha", "to": "flag:f", "type": "gated-by",
                  "origin": "authored"}]
        store.upsert_main("sha0", [alpha0, flag], edges,
                          {"added": [alpha0, flag], "removed": [], "changed": []})
        alpha1 = {**alpha0, "intent": "Alpha now doubles x.",
                  "provenance": {"source_path": "src/m.py", "source_sha": "bbb",
                                 "status": "verified"}}
        store.upsert_main("sha1", [alpha1, flag], edges,
                          {"added": [], "removed": [], "changed": [alpha1]})
        store.close()
        self.brain = Brain(str(self.path), revision="main").load()

    def tearDown(self) -> None:
        self.path.unlink(missing_ok=True)

    def test_history_is_the_intent_timeline(self) -> None:
        h = self.brain.history("src/m.py#alpha")
        self.assertEqual([r["intent"] for r in h],
                         ["Alpha returns x.", "Alpha now doubles x."])
        self.assertEqual([r["sha"] for r in h], ["sha0", "sha1"])

    def test_why_surfaces_provenance_lineage_and_governance(self) -> None:
        w = self.brain.why("src/m.py#alpha")
        self.assertEqual(w["intent"], "Alpha now doubles x.")
        self.assertEqual(w["status"], "verified")       # inferred → verified
        self.assertEqual(w["first_seen_sha"], "sha0")    # born at sha0
        self.assertEqual(w["last_touched_sha"], "sha1")  # last changed at sha1
        self.assertIn("flag:f", w["governed_by"])        # gated-by edge
        self.assertEqual(w["intent_changes"], 2)

    def test_why_missing_entity(self) -> None:
        self.assertIn("error", self.brain.why("nope#nope"))


class WhyJsonModeTests(unittest.TestCase):
    """why() works without sqlite — lineage/governance come from the graph; history is []."""

    def test_why_from_json_graph(self) -> None:
        graph = {"nodes": [{"id": "src/a.py#fn", "type": "function", "title": "fn",
                            "intent": "does a thing",
                            "provenance": {"source_path": "src/a.py", "status": "inferred"}}],
                 "edges": [{"from": "src/a.py#fn", "to": "flag:x", "type": "gated-by"}]}
        brain = Brain("unused")
        brain._graph = graph
        w = brain.why("src/a.py#fn")
        self.assertEqual(w["status"], "inferred")
        self.assertIn("flag:x", w["governed_by"])
        self.assertEqual(w["intent_changes"], 0)         # no sqlite → no history
        self.assertEqual(brain.history("src/a.py#fn"), [])


if __name__ == "__main__":
    unittest.main()