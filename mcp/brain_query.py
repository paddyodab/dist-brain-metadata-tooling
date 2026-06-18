"""Query logic over a materialized brain `graph.json` (stdlib only).

Pure functions so they can be unit-tested without the MCP SDK installed. The
graph source is a local path or an http(s) URL (e.g. the raw graph.json in a
repo's wiki). The MCP server (server.py) is a thin wrapper over this.
"""
from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path


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


class Brain:
    def __init__(self, source: str):
        self.source = str(source)
        self._graph: dict = {"nodes": [], "edges": []}

    def load(self) -> "Brain":
        if self.source.startswith(("http://", "https://")):
            with urllib.request.urlopen(self.source, timeout=15) as r:  # noqa: S310
                self._graph = json.loads(r.read().decode())
        else:
            self._graph = json.loads(Path(self.source).read_text())
        return self

    @property
    def nodes(self) -> list[dict]:
        return self._graph.get("nodes", [])

    @property
    def edges(self) -> list[dict]:
        return self._graph.get("edges", [])

    # ---- queries ----------------------------------------------------------

    def overview(self) -> dict:
        by_type: dict[str, int] = {}
        for n in self.nodes:
            by_type[n["type"]] = by_type.get(n["type"], 0) + 1
        modules = sorted({n["subsystem"] for n in self.nodes if n["type"] in ("function", "method")})
        flags = sorted(n["title"] for n in self.nodes if n["type"] == "flag")
        decisions = [{"id": n["id"], "title": n["title"], "status": n["facts"].get("status")}
                     for n in self.nodes if n["type"] == "decision"]
        return {
            "generated_from_sha": self._graph.get("generated_from_sha"),
            "counts": by_type,
            "modules": modules,
            "flags": flags,
            "decisions": decisions,
        }

    def search(self, query: str, limit: int = 12) -> list[dict]:
        """Match nodes whose id/title/intent contain every query token (AND).

        Single-token queries behave as before (substring match). Multi-word queries
        like "custom aliases" match when each token appears somewhere in the haystack,
        so "custom alias" in intent matches even though the plural differs.
        """
        tokens = [t for t in query.lower().split() if t]
        if not tokens:
            return []

        scored: list[tuple[int, dict]] = []
        for n in self.nodes:
            hay = " ".join(str(x) for x in (n["id"], n.get("title"), n.get("intent"))).lower()
            words = _hay_words(hay)
            if not all(_token_matches(tok, hay, words) for tok in tokens):
                continue
            # Prefer title hits, then id, so the most relevant entities rank first.
            title = (n.get("title") or "").lower()
            title_words = _hay_words(title)
            score = sum(2 if _token_matches(tok, title, title_words) else 1 for tok in tokens)
            scored.append((score, {
                "id": n["id"],
                "type": n["type"],
                "title": n.get("title"),
                "intent": n.get("intent"),
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
            "out": [{"to": e["to"], "type": e["type"]} for e in self.edges if e["from"] == node_id],
            "in": [{"from": e["from"], "type": e["type"]} for e in self.edges if e["to"] == node_id],
        }

    def decisions(self) -> list[dict]:
        return [{"id": n["id"], "title": n["title"], "status": n["facts"].get("status"),
                 "summary": n.get("intent")}
                for n in self.nodes if n["type"] == "decision"]
