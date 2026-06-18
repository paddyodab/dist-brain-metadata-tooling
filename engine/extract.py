#!/usr/bin/env python3
"""Graph extractor (deterministic, stdlib-only) — reusable engine.

Analyzes a target repo (``--root``) and prints {"nodes": [...], "edges": [...]}:
function/method nodes (intent + params/returns/raises/feature/flag), flag nodes
from flags.yml, and `gated-by` / `raises` edges. Paths are emitted relative to
``--root`` so node ids are stable across machines.

Usage: python3 extract.py [--root DIR] [--src DIR] [--flags FILE]
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
from pathlib import Path

from flags_registry import load_flags

LANG = "python"
TAG_RE = re.compile(r"@(\w+)\b")


def parse_tags(docstring: str) -> dict[str, list[str]]:
    tags: dict[str, list[str]] = {}
    current = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        if current is not None:
            tags.setdefault(current, []).append(" ".join(buffer).strip())
        buffer = []

    for raw in docstring.splitlines():
        line = raw.strip()
        m = TAG_RE.match(line)
        if m:
            flush()
            current = m.group(1)
            buffer = [line[m.end():].strip()]
        elif current is not None:
            buffer.append(line)
    flush()
    return tags


def signature_params(fn) -> list[str]:
    a = fn.args
    names = [arg.arg for arg in (a.posonlyargs + a.args + a.kwonlyargs)]
    if a.vararg:
        names.append(a.vararg.arg)
    if a.kwarg:
        names.append(a.kwarg.arg)
    return [n for n in names if n not in ("self", "cls")]


def returns_type(fn) -> str | None:
    if fn.returns is not None:
        text = ast.unparse(fn.returns)
        return None if text == "None" else text
    for node in ast.walk(fn):
        if isinstance(node, ast.Return) and node.value is not None:
            return "<value>"
    return None


def first(tags, key):
    vals = tags.get(key)
    return vals[0].split()[0] if vals and vals[0].split() else None


def extract_file(path: Path, root: Path) -> tuple[list[dict], list[dict]]:
    source = path.read_text()
    tree = ast.parse(source, filename=str(path))
    nodes: list[dict] = []
    edges: list[dict] = []
    rel = path.relative_to(root)
    subsystem = f"{LANG}:{path.stem}"

    def handle(fn, qual: str, kind: str) -> None:
        if fn.name.startswith("_"):
            return
        doc = ast.get_docstring(fn)
        tags = parse_tags(doc) if doc else {}
        # canonical raises = authored @raises (includes propagated exceptions a
        # lexical scan misses); the gate already verified lexical raises ⊆ these.
        raises = sorted({e.split()[0] for e in tags.get("raises", []) if e.split()})
        flag = first(tags, "flag")
        feature = first(tags, "feature")
        segment = ast.get_source_segment(source, fn) or ""
        node_id = f"{rel}#{qual}"
        nodes.append({
            "id": node_id, "type": kind, "title": qual,
            "intent": tags.get("intent", [None])[0],
            "facts": {"params": signature_params(fn), "returns": returns_type(fn),
                      "raises": raises, "feature": feature, "flag": flag},
            "subsystem": subsystem,
            "provenance": {"source_path": str(rel),
                           "source_sha": hashlib.sha1(segment.encode()).hexdigest()[:12],
                           "status": "verified", "extracted_by": "py-extractor@1"},
        })
        for exc in raises:
            edges.append({"from": node_id, "to": f"exception:{exc}", "type": "raises", "origin": "derived"})
        if flag:
            edges.append({"from": node_id, "to": f"flag:{flag}", "type": "gated-by", "origin": "authored"})

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            handle(node, node.name, "function")
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    handle(sub, f"{node.name}.{sub.name}", "method")
    return nodes, edges


def flag_nodes(flags_path: Path) -> list[dict]:
    out = []
    for name, meta in load_flags(flags_path).items():
        blob = json.dumps(meta, sort_keys=True)
        out.append({
            "id": f"flag:{name}", "type": "flag", "title": name,
            "intent": meta.get("description"),
            "facts": {"default": meta.get("default"), "owner": meta.get("owner")},
            "subsystem": "flags",
            "provenance": {"source_path": "flags.yml",
                           "source_sha": hashlib.sha1(blob.encode()).hexdigest()[:12],
                           "status": "verified", "extracted_by": "flags@1"},
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.environ.get("GITHUB_WORKSPACE") or ".")
    ap.add_argument("--src", default=None)
    ap.add_argument("--flags", default=None)
    args = ap.parse_args()

    root = Path(args.root).resolve()
    src_root = Path(args.src).resolve() if args.src else root / "src"
    flags_path = Path(args.flags).resolve() if args.flags else root / "flags.yml"

    nodes = list(flag_nodes(flags_path))
    edges: list[dict] = []
    for f in sorted(src_root.rglob("*.py")):
        n, e = extract_file(f, root)
        nodes.extend(n)
        edges.extend(e)
    print(json.dumps({"nodes": nodes, "edges": edges}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
