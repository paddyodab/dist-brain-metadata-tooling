"""Query logic over a materialized brain (stdlib only).

Sources:
  - graph.json (http(s) URL or local path) — legacy/small-repo export
  - brain.sqlite — canonical store with FTS5 and revisions (preferred at scale)

Multi-repo join applies to JSON sources only in this spike.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

_ENGINE = Path(__file__).resolve().parent.parent / "engine"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from brain_store import DEFAULT_REVISION, BrainStore  # noqa: E402


def _hay_words(hay: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+", hay)


def _token_matches(tok: str, hay: str, words: list[str]) -> bool:
    """True if tok appears in hay, including simple singular/plural variants."""
    if tok in hay:
        return True
    for w in words:
        if tok == w:
            return True
        if tok in (w + "s", w + "es") or w in (tok + "s", tok + "es"):
            return True
    return False


def _slug_from_url(url: str) -> str:
    """Derive a repo slug from a wiki graph.json URL."""
    path = urlparse(url).path.strip("/")
    parts = path.split("/")
    if "wiki" in parts:
        idx = parts.index("wiki")
        if idx + 1 < len(parts):
            return parts[idx + 1].replace(".git", "")
    if parts:
        return parts[-1].replace("graph.json", "").strip("-") or "brain"
    return "brain"


def _slug_from_path(path: str) -> str:
    p = Path(path)
    parent = p.parent.name
    return parent if parent and parent != "." else p.stem or "brain"


def parse_sources(spec: str) -> list[tuple[str, str]]:
    """Parse DIST_BRAIN_GRAPH into (slug, url_or_path) pairs."""
    spec = spec.strip()
    if not spec:
        return [("brain", "brain/graph.json")]
    if spec.startswith("["):
        items = json.loads(spec)
        out: list[tuple[str, str]] = []
        for item in items:
            if isinstance(item, str):
                out.append((_slug_from_url(item), item))
            else:
                url = item["url"]
                slug = item.get("slug") or _slug_from_url(url)
                out.append((slug, url))
        return out
    if "," in spec:
        out = []
        for part in spec.split(","):
            part = part.strip()
            if not part:
                continue
            if "|" in part:
                slug, url = part.split("|", 1)
                out.append((slug.strip(), url.strip()))
            else:
                out.append((
                    _slug_from_url(part) if part.startswith("http") else _slug_from_path(part),
                    part,
                ))
        return out
    return [(
        _slug_from_url(spec) if spec.startswith("http") else _slug_from_path(spec),
        spec,
    )]


def _fetch_graph(url_or_path: str) -> dict:
    if url_or_path.startswith(("http://", "https://")):
        with urllib.request.urlopen(url_or_path, timeout=15) as r:  # noqa: S310
            return json.loads(r.read().decode())
    return json.loads(Path(url_or_path).read_text())


def merge_graphs(sources: list[tuple[str, dict]]) -> dict:
    """Merge multiple graphs with slug-prefixed node ids and remapped edges."""
    nodes: list[dict] = []
    edges: list[dict] = []
    source_meta: list[dict] = []
    for slug, graph in sources:
        prefix = f"{slug}:"
        local_nodes = graph.get("nodes", [])
        id_map: dict[str, str] = {}
        for n in local_nodes:
            old_id = n["id"]
            new_id = old_id if old_id.startswith(prefix) else f"{prefix}{old_id}"
            id_map[old_id] = new_id
            node = {**n, "id": new_id, "source": slug}
            nodes.append(node)
        for e in graph.get("edges", []):
            edges.append({
                **e,
                "from": id_map.get(e["from"], e["from"]),
                "to": id_map.get(e["to"], e["to"]),
                "source": slug,
            })
        source_meta.append({
            "slug": slug,
            "generated_from_sha": graph.get("generated_from_sha"),
            "node_count": len(local_nodes),
            "edge_count": len(graph.get("edges", [])),
        })
    return {
        "schema_version": 1,
        "joined": len(sources) > 1,
        "sources": source_meta,
        "node_count": len(nodes),
        "nodes": nodes,
        "edges": edges,
    }


def _is_sqlite(path: str) -> bool:
    low = path.lower()
    return low.endswith(".sqlite") or low.endswith(".db")


class Brain:
    def __init__(self, source: str, revision: str = DEFAULT_REVISION):
        self.source = str(source)
        self.revision = revision
        self._sources: list[tuple[str, str]] = parse_sources(self.source)
        self._graph: dict = {"nodes": [], "edges": []}
        self._store: BrainStore | None = None

    def load(self) -> "Brain":
        loc = self._sources[0][1]
        if len(self._sources) == 1 and _is_sqlite(loc):
            path = Path(loc)
            if loc.startswith(("http://", "https://")):
                return self._load_sqlite_remote(loc)
            self._store = BrainStore.open(path)
            self._graph = self._store.load_graph(self.revision)
            self._graph["joined"] = False
            self._graph["storage"] = "sqlite"
            self._graph["revisions"] = self._store.list_revisions()
            return self

        loaded: list[tuple[str, dict]] = []
        for slug, src_loc in self._sources:
            loaded.append((slug, _fetch_graph(src_loc)))
        if len(loaded) == 1:
            graph = loaded[0][1]
            graph = {
                **graph,
                "joined": False,
                "storage": "json",
                "sources": [{
                    "slug": loaded[0][0],
                    "generated_from_sha": graph.get("generated_from_sha"),
                    "node_count": len(graph.get("nodes", [])),
                    "edge_count": len(graph.get("edges", [])),
                }],
            }
            self._graph = graph
        else:
            self._graph = merge_graphs(loaded)
            self._graph["storage"] = "json"
        return self

    def _load_sqlite_remote(self, url: str) -> "Brain":
        import tempfile
        with urllib.request.urlopen(url, timeout=30) as r:  # noqa: S310
            data = r.read()
        tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        tmp.write(data)
        tmp.close()
        self._store = BrainStore.open(Path(tmp.name))
        self._graph = self._store.load_graph(self.revision)
        self._graph["joined"] = False
        self._graph["storage"] = "sqlite"
        self._graph["revisions"] = self._store.list_revisions()
        return self

    @property
    def nodes(self) -> list[dict]:
        return self._graph.get("nodes", [])

    @property
    def edges(self) -> list[dict]:
        return self._graph.get("edges", [])

    def list_sources(self) -> list[dict]:
        return list(self._graph.get("sources", []))

    def list_revisions(self) -> list[dict]:
        if self._store:
            return self._store.list_revisions()
        rev = self._graph.get("revision")
        if rev:
            return [{
                "ref": rev,
                "sha": self._graph.get("generated_from_sha"),
                "node_count": self._graph.get("node_count", len(self.nodes)),
                "edge_count": len(self.edges),
                "is_rolling": 1 if rev == DEFAULT_REVISION else 0,
            }]
        return []

    def _filter_nodes(self, nodes: list[dict], source: str | None) -> list[dict]:
        if not source:
            return nodes
        return [n for n in nodes if n.get("source") == source]

    # ---- queries ----------------------------------------------------------

    def overview(self) -> dict:
        by_type: dict[str, int] = {}
        for n in self.nodes:
            by_type[n["type"]] = by_type.get(n["type"], 0) + 1
        modules = sorted({n["subsystem"] for n in self.nodes if n["type"] in ("function", "method")})
        flags = sorted(n["title"] for n in self.nodes if n["type"] == "flag")
        decisions = [{"id": n["id"], "title": n["title"], "status": n["facts"].get("status"),
                      "kind": n["facts"].get("kind", "record"),
                      "enforcement": n["facts"].get("enforcement"),
                      "source": n.get("source")}
                     for n in self.nodes if n["type"] == "decision"]
        return {
            "joined": self._graph.get("joined", False),
            "storage": self._graph.get("storage"),
            "revision": self._graph.get("revision", self.revision),
            "sources": self.list_sources(),
            "revisions": self.list_revisions(),
            "generated_from_sha": self._graph.get("generated_from_sha"),
            "counts": by_type,
            "modules": modules,
            "flags": flags,
            "decisions": decisions,
        }

    def search(self, query: str, limit: int = 12, source: str | None = None) -> list[dict]:
        """Match nodes whose id/title/intent contain every query token (AND)."""
        if self._store and not source:
            return self._store.search(query, revision=self.revision, limit=limit)
        tokens = [t for t in query.lower().split() if t]
        if not tokens:
            return []

        scored: list[tuple[int, dict]] = []
        for n in self._filter_nodes(self.nodes, source):
            hay = " ".join(str(x) for x in (n["id"], n.get("title"), n.get("intent"))).lower()
            words = _hay_words(hay)
            if not all(_token_matches(tok, hay, words) for tok in tokens):
                continue
            title = (n.get("title") or "").lower()
            title_words = _hay_words(title)
            score = sum(2 if _token_matches(tok, title, title_words) else 1 for tok in tokens)
            scored.append((score, {
                "id": n["id"],
                "type": n["type"],
                "title": n.get("title"),
                "intent": n.get("intent"),
                "source": n.get("source"),
            }))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [hit for _, hit in scored[:limit]]

    def get_entity(self, node_id: str) -> dict:
        node = next((n for n in self.nodes if n["id"] == node_id), None)
        if node is None:
            return {"error": f"no entity with id {node_id!r}"}
        return {
            **node,
            "edges_out": [e for e in self.edges if e["from"] == node_id],
            "edges_in": [e for e in self.edges if e["to"] == node_id],
        }

    def neighbors(self, node_id: str) -> dict:
        return {
            "out": [{"to": e["to"], "type": e["type"], "source": e.get("source")}
                    for e in self.edges if e["from"] == node_id],
            "in": [{"from": e["from"], "type": e["type"], "source": e.get("source")}
                   for e in self.edges if e["to"] == node_id],
        }

    def history(self, node_id: str) -> list[dict]:
        """Intent-change timeline for an entity (sqlite brains only; [] otherwise)."""
        if self._store:
            return self._store.history(node_id, revision=self.revision)
        return []

    def why(self, node_id: str) -> dict:
        """Provenance story for an entity: current intent, status (verified|inferred),
        lineage shas, what governs it (flags via gated-by, linked decisions), and how
        many times its intent has changed. Pairs with history() for the timeline."""
        node = next((n for n in self.nodes if n["id"] == node_id), None)
        if node is None:
            return {"error": f"no entity with id {node_id!r}"}
        prov = node.get("provenance") or {}
        governed_by = sorted({
            e["to"] for e in self.edges if e["from"] == node_id
            and (e.get("type") in ("gated-by", "governed-by") or e["to"].startswith("decision:"))
        })
        return {
            "id": node_id,
            "intent": node.get("intent"),
            "status": prov.get("status"),
            "source": prov.get("source_path"),
            "first_seen_sha": node.get("first_seen_sha"),
            "last_touched_sha": node.get("last_touched_sha"),
            "governed_by": governed_by,
            "intent_changes": len(self.history(node_id)),
        }

    def decisions(self, source: str | None = None, kind: str | None = None) -> list[dict]:
        """List decision/ADR nodes. ``kind`` filters to ``record`` or ``constraint``
        (constraint ADRs are the house rules — the rung-2 premises /feature consults)."""
        out = []
        for n in self._filter_nodes(self.nodes, source):
            if n["type"] != "decision":
                continue
            n_kind = n["facts"].get("kind", "record")
            if kind and n_kind != kind:
                continue
            out.append({"id": n["id"], "title": n["title"],
                        "status": n["facts"].get("status"),
                        "kind": n_kind, "enforcement": n["facts"].get("enforcement"),
                        "applies_to": n["facts"].get("applies_to"),
                        "summary": n.get("intent"), "source": n.get("source")})
        return out