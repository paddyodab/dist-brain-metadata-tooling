"""Query logic over a materialized brain `graph.json` (stdlib only).

Pure functions so they can be unit-tested without the MCP SDK installed. The
graph source is a local path or an http(s) URL (e.g. the raw graph.json in a
repo's wiki). The MCP server (server.py) is a thin wrapper over this.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path


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
        q = query.lower()
        out = []
        for n in self.nodes:
            hay = " ".join(str(x) for x in (n["id"], n.get("title"), n.get("intent"))).lower()
            if q in hay:
                out.append({"id": n["id"], "type": n["type"],
                            "title": n.get("title"), "intent": n.get("intent")})
            if len(out) >= limit:
                break
        return out

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
