#!/usr/bin/env python3
"""Local intent-coverage report (pytest-cov analogue for metadata).

Prints a terminal summary: % public symbols with @intent, per-module breakdown,
optional @feature counts, inference-queue backlog, and where the local wiki lives.

Usage:
  python3 brain_status.py --root . --src app
  python3 brain_status.py --root . --src app --brain /tmp/sandbox-brain
"""
from __future__ import annotations

import argparse
import json
import os
import re
from collections import defaultdict
from pathlib import Path

from extract import extract_file  # noqa: E402 — same package


def collect_entities(src_root: Path, root: Path) -> list[dict]:
    nodes: list[dict] = []
    for path in sorted(src_root.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        n, _ = extract_file(path, root)
        nodes.extend(n)
    return [n for n in nodes if n["type"] in ("function", "method")]


def queue_backlog(root: Path) -> tuple[int | None, str | None]:
    q = root / "inference-queue.md"
    if not q.exists():
        return None, None
    text = q.read_text()
    m = re.search(r"symbols without `@intent`:\s*(\d+)", text)
    pending = int(m.group(1)) if m else None
    if pending == 0:
        return 0, None
    if re.search(r"\*\*Status:\*\*.*ratified", text, re.I):
        return 0, str(q.relative_to(root))
    drafts = len(re.findall(r"^### `", text, re.M))
    return drafts or pending, str(q.relative_to(root))


def bar(ratio: float, width: int = 24) -> str:
    filled = int(ratio * width)
    return "█" * filled + "░" * (width - filled)


def main() -> int:
    ap = argparse.ArgumentParser(description="Local metadata coverage report")
    ap.add_argument("--root", default=os.environ.get("GITHUB_WORKSPACE") or ".")
    ap.add_argument("--src", default=None)
    ap.add_argument("--brain", default=None, help="materialized brain dir (for wiki path + state)")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    src_root = Path(args.src).resolve() if args.src else root / "src"
    brain_dir = Path(args.brain).resolve() if args.brain else None

    entities = collect_entities(src_root, root)
    total = len(entities)
    with_intent = [e for e in entities if (e.get("intent") or "").strip()]
    with_feature = [e for e in entities if (e["facts"].get("feature") or "").strip()]
    missing = [e for e in entities if not (e.get("intent") or "").strip()]

    ratio = len(with_intent) / total if total else 0.0
    queue_n, queue_path = queue_backlog(root)

    by_mod: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "intent": 0, "feature": 0})
    for e in entities:
        mod = Path(e["id"].split("#")[0]).stem
        by_mod[mod]["total"] += 1
        if (e.get("intent") or "").strip():
            by_mod[mod]["intent"] += 1
        if (e["facts"].get("feature") or "").strip():
            by_mod[mod]["feature"] += 1

    print()
    print("  METADATA COVERAGE (local)")
    print("  " + "─" * 52)
    print(f"  @intent   {len(with_intent):4d} / {total:4d}  ({ratio:5.1%})  {bar(ratio)}")
    feat_ratio = len(with_feature) / total if total else 0.0
    print(f"  @feature  {len(with_feature):4d} / {total:4d}  ({feat_ratio:5.1%})  {bar(feat_ratio)}")
    print()

    if queue_n:
        where = f" ({queue_path})" if queue_path else ""
        print(f"  ⏳ inference queue: {queue_n} draft(s) awaiting ratification{where}")
    elif queue_n == 0 and queue_path:
        print(f"  ✓ inference queue: clear ({queue_path})")
    print()

    print("  Per module:")
    for mod in sorted(by_mod):
        s = by_mod[mod]
        pct = s["intent"] / s["total"] if s["total"] else 0
        flag = " ✓" if s["intent"] == s["total"] else ""
        print(f"    {mod:28s}  {s['intent']:3d}/{s['total']:3d} intent  ({pct:5.1%}){flag}")
    print()

    if missing:
        show = missing[:12]
        print(f"  Missing @intent ({len(missing)}):")
        for e in show:
            print(f"    · {e['id']}")
        if len(missing) > len(show):
            print(f"    · … and {len(missing) - len(show)} more")
        print()

    if brain_dir and brain_dir.is_dir():
        state_path = brain_dir / "state.json"
        sha = "—"
        if state_path.exists():
            sha = json.loads(state_path.read_text()).get("last_sha", "—")
        print("  Local wiki (same as GH wiki after merge):")
        print(f"    {brain_dir}/Home.md")
        print(f"    {brain_dir}/agent-context.md")
        print(f"    {brain_dir}/Changelog.md   (last sha: {sha})")
        print()

    print("  Next:")
    if missing:
        print("    scripts/brain infer <module>     # draft queue")
    if queue_n:
        print("    ratify inference-queue.md        # then materialize")
    print("    scripts/brain materialize        # refresh local wiki + sqlite")
    print("    scripts/brain status             # this report")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())