#!/usr/bin/env python3
"""Render-less, diff-scoped brain refresh — the per-turn / per-commit fast path.

Updates ``brain.sqlite`` (the canonical store + meaning-stream) from only the files
git says changed, and skips the wiki render entirely. This is what a Stop hook runs
on green during a long ``/goal`` run so the next turn queries the work it just wrote,
without waiting for the merge-to-``main`` materialize.

Layering: git diff is the COARSE file filter; each node's ``source_sha`` (set in
extract_file) is the FINE node filter — so an unrelated edit re-parses a file but
yields zero changed nodes. ``intent_history`` / lineage stay correct because they fire
inside ``BrainStore.upsert_main``.

Falls back to a FULL extract when there is no prior ``main`` revision (first run).

Usage:
  python3 refresh_brain.py --root . --brain /tmp/brain --src app --include-working
  python3 refresh_brain.py --root . --brain /tmp/brain --since main
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

from brain_store import DEFAULT_REVISION, BrainStore
from extract import extract_full, extract_scoped, git_changed_paths


def git_sha(root: Path) -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root,
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return "nogit"


def _source_sha(node: dict) -> str | None:
    return (node.get("provenance") or {}).get("source_sha")


def scoped_delta(prev_nodes: list[dict], new_nodes: list[dict],
                 scope: dict, flags_name: str) -> dict:
    """diff_nodes, but removals limited to what this run re-extracted, so unchanged
    files are never touched. Small categories (flags/decisions/house-rules) count as
    in-scope only when their file actually changed — otherwise their absence from ``new``
    would be misread as a removal."""
    touched = set(scope["paths"]) | set(scope["deleted"])
    flags_in_scope = any(Path(p).name == flags_name for p in touched)
    decisions_in_scope = any(p.startswith("decisions/") for p in touched)
    house_rules_in_scope = any(p.startswith("house-rules/") for p in touched)

    def in_scope(node: dict) -> bool:
        sp = (node.get("provenance") or {}).get("source_path")
        if sp in touched:
            return True
        sub = node.get("subsystem")
        return (
            (sub == "flags" and flags_in_scope)
            or (sub == "decisions" and decisions_in_scope)
            or (sub == "house-rules" and house_rules_in_scope)
        )

    prev = {n["id"]: n for n in prev_nodes if in_scope(n)}
    new = {n["id"]: n for n in new_nodes}
    return {
        "added": [new[i] for i in new if i not in prev],
        "changed": [new[i] for i in new if i in prev and _source_sha(new[i]) != _source_sha(prev[i])],
        "removed": [{"id": i} for i in prev if i not in new],
    }


def _read_state(brain: Path) -> dict:
    f = brain / "state.json"
    return json.loads(f.read_text()) if f.exists() else {}


def _write_state(brain: Path, state: dict) -> None:
    (brain / "state.json").write_text(json.dumps(state, indent=2))


def main() -> int:
    ap = argparse.ArgumentParser(description="Diff-scoped, render-less brain refresh")
    ap.add_argument("--root", default=os.environ.get("GITHUB_WORKSPACE") or ".")
    ap.add_argument("--brain", required=True, help="brain dir holding brain.sqlite + state.json")
    ap.add_argument("--src", default=None)
    ap.add_argument("--flags", default=None)
    ap.add_argument("--since", default=None,
                    help="git ref to diff against (default: state.last_sha, else HEAD~1)")
    ap.add_argument("--include-working", action="store_true",
                    help="also include unstaged + staged edits (mid-turn freshness)")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    brain = Path(args.brain).resolve()
    brain.mkdir(parents=True, exist_ok=True)
    src_root = Path(args.src).resolve() if args.src else root / "src"
    flags_path = Path(args.flags).resolve() if args.flags else root / "flags.yml"

    store = BrainStore.open(brain / "brain.sqlite")
    prev = store.load_graph(DEFAULT_REVISION)
    sha = git_sha(root)
    state = _read_state(brain)

    # First run (no prior main revision) → full extract; can't diff against nothing.
    if not prev["nodes"]:
        result = extract_full(root, src_root, flags_path)
        delta = {"added": result["nodes"], "removed": [], "changed": []}
        store.upsert_main(sha, result["nodes"], result["edges"], delta)
        store.close()
        _write_state(brain, {**state, "last_sha": sha, "brain_store": "brain.sqlite",
                             "revision": DEFAULT_REVISION})
        print(f"brain refreshed (full, first run) @ {sha}: {len(result['nodes'])} nodes")
        return 0

    since = args.since or state.get("last_sha") or "HEAD~1"
    changed, deleted = git_changed_paths(root, since, args.include_working)
    if not changed and not deleted:
        store.close()
        print(f"brain: no changes since {since} — no-op")
        return 0

    result = extract_scoped(root, src_root, flags_path, changed, deleted)
    delta = scoped_delta(prev["nodes"], result["nodes"], result["scope"], flags_path.name)
    store.upsert_main(sha, result["nodes"], result["edges"], delta)
    store.close()
    _write_state(brain, {**state, "last_sha": sha, "brain_store": "brain.sqlite",
                         "revision": DEFAULT_REVISION})
    print(f"brain refreshed @ {sha} (since {since}): "
          f"+{len(delta['added'])} ~{len(delta['changed'])} -{len(delta['removed'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
