"""SQLite brain store — canonical property graph with FTS5 and revisions.

Git is the WAL; this is the materialized view. ``main`` is the rolling revision
(full entity set, incrementally upserted). Tags are frozen snapshots copied from
main or materialized at a pinned SHA.

Usage:
  store = BrainStore.open(Path("brain/brain.sqlite"))
  store.upsert_main(sha, nodes, edges, delta)
  store.snapshot_revision("v1.0", sha)   # copy main → tag
  graph = store.load_graph("main")
"""
from __future__ import annotations

import json
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
DEFAULT_REVISION = "main"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _hay_words(hay: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+", hay)


def _token_matches(tok: str, hay: str, words: list[str]) -> bool:
    if tok in hay:
        return True
    for w in words:
        if tok == w:
            return True
        if tok in (w + "s", w + "es") or w in (tok + "s", tok + "es"):
            return True
    return False


def _fts_quote(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


class BrainStore:
    def __init__(self, conn: sqlite3.Connection, path: Path):
        self.conn = conn
        self.path = path
        self.conn.row_factory = sqlite3.Row

    @classmethod
    def open(cls, path: Path) -> BrainStore:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path))
        store = cls(conn, path)
        store.ensure_schema()
        return store

    def ensure_schema(self) -> None:
        self.conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS meta (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS revisions (
              ref TEXT PRIMARY KEY,
              sha TEXT NOT NULL,
              node_count INTEGER NOT NULL DEFAULT 0,
              edge_count INTEGER NOT NULL DEFAULT 0,
              materialized_at TEXT NOT NULL,
              is_rolling INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS nodes (
              revision_ref TEXT NOT NULL,
              id TEXT NOT NULL,
              type TEXT NOT NULL,
              title TEXT,
              intent TEXT,
              subsystem TEXT,
              facts_json TEXT NOT NULL DEFAULT '{}',
              provenance_json TEXT NOT NULL DEFAULT '{}',
              source_path TEXT,
              source_sha TEXT,
              provenance_status TEXT NOT NULL DEFAULT 'verified',
              first_seen_sha TEXT,
              last_touched_sha TEXT,
              PRIMARY KEY (revision_ref, id),
              FOREIGN KEY (revision_ref) REFERENCES revisions(ref) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS edges (
              revision_ref TEXT NOT NULL,
              from_id TEXT NOT NULL,
              to_id TEXT NOT NULL,
              edge_type TEXT NOT NULL,
              origin TEXT,
              PRIMARY KEY (revision_ref, from_id, to_id, edge_type),
              FOREIGN KEY (revision_ref) REFERENCES revisions(ref) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS intent_history (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              revision_ref TEXT NOT NULL,
              entity_id TEXT NOT NULL,
              sha TEXT NOT NULL,
              intent TEXT NOT NULL,
              recorded_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_nodes_type
              ON nodes(revision_ref, type);
            CREATE INDEX IF NOT EXISTS idx_nodes_subsystem
              ON nodes(revision_ref, subsystem);
            CREATE INDEX IF NOT EXISTS idx_edges_from
              ON edges(revision_ref, from_id);
            CREATE INDEX IF NOT EXISTS idx_edges_to
              ON edges(revision_ref, to_id);
            """
        )
        # FTS5 — separate execute; may fail on minimal sqlite builds
        try:
            self.conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
                  entity_id UNINDEXED,
                  revision_ref UNINDEXED,
                  title,
                  intent,
                  content='',
                  tokenize='porter'
                )
                """
            )
        except sqlite3.OperationalError:
            pass
        self.conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self.conn.commit()

    def list_revisions(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT ref, sha, node_count, edge_count, materialized_at, is_rolling "
            "FROM revisions ORDER BY is_rolling DESC, ref"
        ).fetchall()
        return [dict(r) for r in rows]

    def _node_row(self, revision: str, node: dict, sha: str, prev: dict | None) -> tuple:
        prov = node.get("provenance") or {}
        status = prov.get("status") or "verified"
        source_sha = prov.get("source_sha") or ""
        first = (prev or {}).get("first_seen_sha") or sha
        last = sha if prev is None or source_sha != prev.get("source_sha") else prev.get("last_touched_sha") or sha
        return (
            revision,
            node["id"],
            node["type"],
            node.get("title"),
            node.get("intent"),
            node.get("subsystem"),
            json.dumps(node.get("facts") or {}),
            json.dumps(prov),
            prov.get("source_path"),
            source_sha,
            status,
            first,
            last,
        )

    def _upsert_fts(self, revision: str, entity_id: str, title: str, intent: str) -> None:
        try:
            self.conn.execute(
                "DELETE FROM nodes_fts WHERE revision_ref=? AND entity_id=?",
                (revision, entity_id),
            )
            self.conn.execute(
                "INSERT INTO nodes_fts(entity_id, revision_ref, title, intent) VALUES (?,?,?,?)",
                (entity_id, revision, title or "", intent or ""),
            )
        except sqlite3.OperationalError:
            pass

    def _delete_fts(self, revision: str, entity_id: str) -> None:
        try:
            self.conn.execute(
                "DELETE FROM nodes_fts WHERE revision_ref=? AND entity_id=?",
                (revision, entity_id),
            )
        except sqlite3.OperationalError:
            pass

    def _record_intent_change(self, revision: str, entity_id: str, sha: str,
                              old_intent: str | None, new_intent: str | None) -> None:
        if old_intent == new_intent:
            return
        if new_intent:
            self.conn.execute(
                "INSERT INTO intent_history(revision_ref, entity_id, sha, intent, recorded_at) "
                "VALUES (?,?,?,?,?)",
                (revision, entity_id, sha, new_intent, _now()),
            )

    def upsert_main(
        self,
        sha: str,
        nodes: list[dict],
        edges: list[dict],
        delta: dict | None = None,
    ) -> None:
        """Incrementally update rolling ``main`` revision (full graph, delta-driven work)."""
        revision = DEFAULT_REVISION
        stamp = _now()
        prev_rows = {
            r["id"]: dict(r)
            for r in self.conn.execute(
                "SELECT id, source_sha, first_seen_sha, last_touched_sha, intent "
                "FROM nodes WHERE revision_ref=?",
                (revision,),
            ).fetchall()
        }
        if not prev_rows:
            delta = {
                "added": list(nodes),
                "removed": [],
                "changed": [],
            }
        elif delta is None:
            new_ids = {n["id"] for n in nodes}
            old_ids = set(prev_rows)
            delta = {
                "added": [n for n in nodes if n["id"] not in old_ids],
                "removed": [{"id": i} for i in old_ids - new_ids],
                "changed": [
                    n for n in nodes
                    if n["id"] in old_ids
                    and (n.get("provenance") or {}).get("source_sha")
                    != prev_rows[n["id"]].get("source_sha")
                ],
            }

        with self.conn:
            self.conn.execute(
                "INSERT INTO revisions(ref, sha, node_count, edge_count, materialized_at, is_rolling) "
                "VALUES (?, ?, ?, ?, ?, 1) "
                "ON CONFLICT(ref) DO UPDATE SET "
                "sha=excluded.sha, node_count=excluded.node_count, edge_count=excluded.edge_count, "
                "materialized_at=excluded.materialized_at",
                (revision, sha, len(nodes), len(edges), stamp),
            )
            for rem in delta.get("removed", []):
                eid = rem["id"] if isinstance(rem, dict) else rem
                self.conn.execute(
                    "DELETE FROM nodes WHERE revision_ref=? AND id=?",
                    (revision, eid),
                )
                self.conn.execute(
                    "DELETE FROM edges WHERE revision_ref=? AND (from_id=? OR to_id=?)",
                    (revision, eid, eid),
                )
                self._delete_fts(revision, eid)

            touched = delta.get("added", []) + delta.get("changed", [])
            touched_ids = {n["id"] for n in touched}
            for node in touched:
                prev = prev_rows.get(node["id"])
                self._record_intent_change(
                    revision, node["id"], sha,
                    (prev or {}).get("intent"), node.get("intent"),
                )
                self.conn.execute(
                    "INSERT INTO nodes("
                    "revision_ref, id, type, title, intent, subsystem, facts_json, "
                    "provenance_json, source_path, source_sha, provenance_status, "
                    "first_seen_sha, last_touched_sha"
                    ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(revision_ref, id) DO UPDATE SET "
                    "type=excluded.type, title=excluded.title, intent=excluded.intent, "
                    "subsystem=excluded.subsystem, facts_json=excluded.facts_json, "
                    "provenance_json=excluded.provenance_json, source_path=excluded.source_path, "
                    "source_sha=excluded.source_sha, provenance_status=excluded.provenance_status, "
                    "first_seen_sha=excluded.first_seen_sha, last_touched_sha=excluded.last_touched_sha",
                    self._node_row(revision, node, sha, prev),
                )
                self._upsert_fts(revision, node["id"], node.get("title") or "", node.get("intent") or "")

            # Full edge replace for touched endpoints + global sync on first run
            if not prev_rows:
                self.conn.execute("DELETE FROM edges WHERE revision_ref=?", (revision,))
                for e in edges:
                    self.conn.execute(
                        "INSERT OR REPLACE INTO edges(revision_ref, from_id, to_id, edge_type, origin) "
                        "VALUES (?,?,?,?,?)",
                        (revision, e["from"], e["to"], e["type"], e.get("origin")),
                    )
            else:
                if touched_ids:
                    placeholders = ",".join("?" * len(touched_ids))
                    self.conn.execute(
                        f"DELETE FROM edges WHERE revision_ref=? AND "
                        f"(from_id IN ({placeholders}) OR to_id IN ({placeholders}))",
                        (revision, *touched_ids, *touched_ids),
                    )
                for e in edges:
                    if touched_ids and e["from"] not in touched_ids and e["to"] not in touched_ids:
                        continue
                    self.conn.execute(
                        "INSERT OR REPLACE INTO edges(revision_ref, from_id, to_id, edge_type, origin) "
                        "VALUES (?,?,?,?,?)",
                        (revision, e["from"], e["to"], e["type"], e.get("origin")),
                    )

            # Counts reflect the TABLE, not the call's params — so a scoped (diff-only)
            # upsert records the same totals as a full one. Keeps `main` stats correct
            # whether the caller passed the whole graph or just the touched slice.
            ncount = self.conn.execute(
                "SELECT COUNT(*) FROM nodes WHERE revision_ref=?", (revision,)
            ).fetchone()[0]
            ecount = self.conn.execute(
                "SELECT COUNT(*) FROM edges WHERE revision_ref=?", (revision,)
            ).fetchone()[0]
            self.conn.execute(
                "UPDATE revisions SET node_count=?, edge_count=? WHERE ref=?",
                (ncount, ecount, revision),
            )

    def snapshot_revision(self, tag_ref: str, sha: str, from_ref: str = DEFAULT_REVISION) -> None:
        """Copy a frozen snapshot (e.g. release tag) from ``from_ref``."""
        stamp = _now()
        with self.conn:
            self.conn.execute("DELETE FROM nodes WHERE revision_ref=?", (tag_ref,))
            self.conn.execute("DELETE FROM edges WHERE revision_ref=?", (tag_ref,))
            try:
                self.conn.execute(
                    "DELETE FROM nodes_fts WHERE revision_ref=?", (tag_ref,)
                )
            except sqlite3.OperationalError:
                pass
            self.conn.execute(
                "INSERT INTO nodes SELECT "
                "? AS revision_ref, id, type, title, intent, subsystem, facts_json, "
                "provenance_json, source_path, source_sha, provenance_status, "
                "first_seen_sha, last_touched_sha FROM nodes WHERE revision_ref=?",
                (tag_ref, from_ref),
            )
            self.conn.execute(
                "INSERT INTO edges SELECT "
                "? AS revision_ref, from_id, to_id, edge_type, origin FROM edges WHERE revision_ref=?",
                (tag_ref, from_ref),
            )
            try:
                self.conn.execute(
                    "INSERT INTO nodes_fts(entity_id, revision_ref, title, intent) "
                    "SELECT entity_id, ?, title, intent FROM nodes_fts WHERE revision_ref=?",
                    (tag_ref, from_ref),
                )
            except sqlite3.OperationalError:
                for row in self.conn.execute(
                    "SELECT id, title, intent FROM nodes WHERE revision_ref=?",
                    (tag_ref,),
                ):
                    self._upsert_fts(tag_ref, row["id"], row["title"] or "", row["intent"] or "")
            ncount = self.conn.execute(
                "SELECT COUNT(*) FROM nodes WHERE revision_ref=?", (tag_ref,)
            ).fetchone()[0]
            ecount = self.conn.execute(
                "SELECT COUNT(*) FROM edges WHERE revision_ref=?", (tag_ref,)
            ).fetchone()[0]
            self.conn.execute(
                "INSERT INTO revisions(ref, sha, node_count, edge_count, materialized_at, is_rolling) "
                "VALUES (?, ?, ?, ?, ?, 0) "
                "ON CONFLICT(ref) DO UPDATE SET "
                "sha=excluded.sha, node_count=excluded.node_count, edge_count=excluded.edge_count, "
                "materialized_at=excluded.materialized_at, is_rolling=0",
                (tag_ref, sha, ncount, ecount, stamp),
            )

    def _row_to_node(self, row: sqlite3.Row) -> dict:
        prov = json.loads(row["provenance_json"] or "{}")
        if not prov:
            prov = {
                "source_path": row["source_path"],
                "source_sha": row["source_sha"],
                "status": row["provenance_status"],
            }
        return {
            "id": row["id"],
            "type": row["type"],
            "title": row["title"],
            "intent": row["intent"],
            "subsystem": row["subsystem"],
            "facts": json.loads(row["facts_json"] or "{}"),
            "provenance": prov,
            "first_seen_sha": row["first_seen_sha"],
            "last_touched_sha": row["last_touched_sha"],
        }

    def load_graph(self, revision: str = DEFAULT_REVISION) -> dict:
        rev = self.conn.execute(
            "SELECT * FROM revisions WHERE ref=?", (revision,)
        ).fetchone()
        if rev is None:
            return {
                "schema_version": SCHEMA_VERSION,
                "revision": revision,
                "generated_from_sha": None,
                "nodes": [],
                "edges": [],
            }
        nodes = [
            self._row_to_node(r)
            for r in self.conn.execute(
                "SELECT * FROM nodes WHERE revision_ref=? ORDER BY id",
                (revision,),
            )
        ]
        edges = [
            {
                "from": r["from_id"],
                "to": r["to_id"],
                "type": r["edge_type"],
                "origin": r["origin"],
            }
            for r in self.conn.execute(
                "SELECT * FROM edges WHERE revision_ref=?",
                (revision,),
            )
        ]
        return {
            "schema_version": SCHEMA_VERSION,
            "revision": revision,
            "generated_from_sha": rev["sha"],
            "node_count": len(nodes),
            "nodes": nodes,
            "edges": edges,
        }

    def _search_scan(self, revision: str, tokens: list[str], limit: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, type, title, intent FROM nodes WHERE revision_ref=?",
            (revision,),
        ).fetchall()
        scored: list[tuple[int, dict]] = []
        for r in rows:
            hay = " ".join(str(x) for x in (r["id"], r["title"], r["intent"])).lower()
            words = _hay_words(hay)
            if not all(_token_matches(tok, hay, words) for tok in tokens):
                continue
            title = (r["title"] or "").lower()
            title_words = _hay_words(title)
            score = sum(2 if _token_matches(tok, title, title_words) else 1 for tok in tokens)
            scored.append((score, {
                "id": r["id"],
                "type": r["type"],
                "title": r["title"],
                "intent": r["intent"],
            }))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [h for _, h in scored[:limit]]

    def search(self, query: str, revision: str = DEFAULT_REVISION, limit: int = 12) -> list[dict]:
        tokens = [t for t in query.lower().split() if t]
        if not tokens:
            return []
        # FTS5 for candidate narrowing at scale; Python AND filter for parity (plural/stem)
        fts_hits: list[dict] = []
        try:
            match = " OR ".join(_fts_quote(t) for t in tokens)
            rows = self.conn.execute(
                "SELECT n.id, n.type, n.title, n.intent FROM nodes_fts f "
                "JOIN nodes n ON n.id=f.entity_id AND n.revision_ref=f.revision_ref "
                "WHERE f.revision_ref=? AND nodes_fts MATCH ? LIMIT ?",
                (revision, match, max(limit * 8, 96)),
            ).fetchall()
            for r in rows:
                fts_hits.append({
                    "id": r["id"],
                    "type": r["type"],
                    "title": r["title"],
                    "intent": r["intent"],
                })
        except sqlite3.OperationalError:
            return self._search_scan(revision, tokens, limit)

        if not fts_hits:
            return self._search_scan(revision, tokens, limit)

        scored: list[tuple[int, dict]] = []
        for h in fts_hits:
            hay = " ".join(str(x) for x in (h["id"], h.get("title"), h.get("intent"))).lower()
            words = _hay_words(hay)
            if not all(_token_matches(tok, hay, words) for tok in tokens):
                continue
            title = (h.get("title") or "").lower()
            title_words = _hay_words(title)
            score = sum(2 if _token_matches(tok, title, title_words) else 1 for tok in tokens)
            scored.append((score, h))
        if not scored:
            return self._search_scan(revision, tokens, limit)
        scored.sort(key=lambda x: x[0], reverse=True)
        return [h for _, h in scored[:limit]]

    def render_features_md(self, revision: str = DEFAULT_REVISION) -> str:
        """SQL-backed human projection: Features.md body (without footer)."""
        flags = self.conn.execute(
            "SELECT * FROM nodes WHERE revision_ref=? AND type='flag' ORDER BY title",
            (revision,),
        ).fetchall()
        lines = [
            "# Features",
            "",
            "Each feature is toggled by a flag in `flags.yml`. To turn a feature on/off, flip its flag.",
            "",
            "_Rendered from `brain.sqlite` (FTS-indexed canonical store)._",
            "",
        ]
        for fl in flags:
            facts = json.loads(fl["facts_json"] or "{}")
            gated = self.conn.execute(
                "SELECT n.title, n.id FROM edges e "
                "JOIN nodes n ON n.id=e.from_id AND n.revision_ref=e.revision_ref "
                "WHERE e.revision_ref=? AND e.to_id=? AND e.edge_type='gated-by' "
                "ORDER BY n.title",
                (revision, fl["id"]),
            ).fetchall()
            gates = ", ".join(f"`{r['title']}`" for r in gated) or "—"
            feature = None
            for g in gated:
                row = self.conn.execute(
                    "SELECT facts_json FROM nodes WHERE revision_ref=? AND id=?",
                    (revision, g["id"]),
                ).fetchone()
                if row:
                    f = json.loads(row["facts_json"] or "{}")
                    if f.get("feature"):
                        feature = f["feature"]
                        break
            feature = feature or fl["title"]
            page = f"Runbook-{feature}"
            lines += [
                f"## `{fl['title']}`",
                "",
                fl["intent"] or "_(no description)_",
                "",
                f"- **default:** `{facts.get('default')}`",
                f"- **owner:** {facts.get('owner') or '—'}",
                f"- **gates:** {gates}",
                f"- **runbook:** [{feature}]({page})",
                "",
            ]
        return "\n".join(lines)

    def close(self) -> None:
        self.conn.close()


def export_graph_json(graph: dict, path: Path) -> None:
    """Optional small-repo export — not for large-scale agent use."""
    path.write_text(json.dumps({
        "schema_version": graph.get("schema_version", SCHEMA_VERSION),
        "generated_from_sha": graph.get("generated_from_sha"),
        "revision": graph.get("revision"),
        "node_count": graph.get("node_count", len(graph.get("nodes", []))),
        "nodes": graph.get("nodes", []),
        "edges": graph.get("edges", []),
    }, indent=2))