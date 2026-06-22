#!/usr/bin/env python3
"""Generate a large synthetic brain for scale benchmarks.

Usage:
  python3 generate_brain_fixture.py --nodes 10000 --out /tmp/large-brain.sqlite
"""
from __future__ import annotations

import argparse
import hashlib
import time
from pathlib import Path

from brain_store import BrainStore


def synthetic_graph(count: int) -> tuple[list[dict], list[dict]]:
    nodes: list[dict] = []
    edges: list[dict] = []
    for i in range(count):
        mod = f"feature_{i % 50}"
        nid = f"src/app/{mod}.py#fn_{i}"
        nodes.append({
            "id": nid,
            "type": "function",
            "title": f"fn_{i}",
            "intent": f"Handle billing workflow step {i} for custom aliases and analytics.",
            "subsystem": f"python:{mod}",
            "facts": {"params": ["store", "code"], "returns": "str", "raises": ["NotFound"], "feature": mod},
            "provenance": {
                "source_path": f"src/app/{mod}.py",
                "source_sha": hashlib.sha1(nid.encode()).hexdigest()[:12],
                "status": "verified",
            },
        })
    flag_id = "flag:enable_feature_0"
    nodes.append({
        "id": flag_id,
        "type": "flag",
        "title": "enable_feature_0",
        "intent": "Gate feature_0 rollout.",
        "subsystem": "flags",
        "facts": {"default": False, "owner": "platform"},
        "provenance": {"source_path": "flags.yml", "source_sha": "abc", "status": "verified"},
    })
    for i in range(0, min(500, count), 10):
        edges.append({
            "from": f"src/app/feature_{i % 50}.py#fn_{i}",
            "to": flag_id,
            "type": "gated-by",
            "origin": "authored",
        })
    return nodes, edges


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nodes", type=int, default=10_000)
    ap.add_argument("--out", default="/tmp/large-brain.sqlite")
    args = ap.parse_args()

    out = Path(args.out)
    if out.exists():
        out.unlink()
    nodes, edges = synthetic_graph(args.nodes)
    store = BrainStore.open(out)
    store.upsert_main("fixture", nodes, edges, {"added": nodes, "removed": [], "changed": []})

    t0 = time.perf_counter()
    hits = store.search("billing custom", limit=12)
    search_ms = (time.perf_counter() - t0) * 1000

    graph = store.load_graph("main")
    t1 = time.perf_counter()
    _ = store.search("analytics", limit=12)
    search2_ms = (time.perf_counter() - t1) * 1000

    print(f"Wrote {out}  ({len(graph['nodes'])} nodes, {len(graph['edges'])} edges)")
    print(f"search('billing custom'): {len(hits)} hits in {search_ms:.1f}ms")
    print(f"search('analytics'): {search2_ms:.1f}ms")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())