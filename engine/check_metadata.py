#!/usr/bin/env python3
"""Tier-1 metadata gate (deterministic, stdlib-only) — reusable engine.

Analyzes a *target* repo (``--root``, defaults to $GITHUB_WORKSPACE) so the same
engine can gate any consumer repo. Verifies each public function's contract:

  * @intent present
  * @param names == the signature's parameters
  * @returns present when the function returns a value
  * @raises declares every exception raised *lexically* in the body
  * @flag (if present) names a flag defined in flags.yml

Usage: python3 check_metadata.py [--root DIR] [--src DIR] [--flags FILE]
"""
from __future__ import annotations

import argparse
import ast
import os
import re
from pathlib import Path

from flags_registry import load_flags

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


def signature_params(fn) -> set[str]:
    a = fn.args
    names = [arg.arg for arg in (a.posonlyargs + a.args + a.kwonlyargs)]
    if a.vararg:
        names.append(a.vararg.arg)
    if a.kwarg:
        names.append(a.kwarg.arg)
    return {n for n in names if n not in ("self", "cls")}


def documented_params(tags) -> set[str]:
    return {e.split()[0].rstrip(":") for e in tags.get("param", []) if e.split()}


def raised_types(fn) -> set[str]:
    types: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Raise) and node.exc is not None:
            exc = node.exc
            if isinstance(exc, ast.Call):
                exc = exc.func
            if isinstance(exc, ast.Name):
                types.add(exc.id)
            elif isinstance(exc, ast.Attribute):
                types.add(exc.attr)
    return types


def returns_value(fn) -> bool:
    if fn.returns is not None:
        ann = fn.returns
        if isinstance(ann, ast.Constant) and ann.value is None:
            return False
        if isinstance(ann, ast.Name) and ann.id == "None":
            return False
        return True
    return any(isinstance(n, ast.Return) and n.value is not None for n in ast.walk(fn))


def check_file(path: Path, root: Path, known_flags: set[str]) -> list[str]:
    errors: list[str] = []
    tree = ast.parse(path.read_text(), filename=str(path))
    funcs = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.append((node, node.name))
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    funcs.append((sub, f"{node.name}.{sub.name}"))

    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = path
    for fn, qual in funcs:
        if fn.name.startswith("_"):
            continue
        loc = f"{rel}:{fn.lineno} {qual}()"
        doc = ast.get_docstring(fn)
        if not doc:
            errors.append(f"{loc}: public function has no docstring/contract")
            continue
        tags = parse_tags(doc)
        if not tags.get("intent"):
            errors.append(f"{loc}: missing @intent")
        sig, documented = signature_params(fn), documented_params(tags)
        if sig - documented:
            errors.append(f"{loc}: @param missing for {sorted(sig - documented)}")
        if documented - sig:
            errors.append(f"{loc}: @param documents unknown {sorted(documented - sig)}")
        if returns_value(fn) and not tags.get("returns"):
            errors.append(f"{loc}: returns a value but has no @returns")
        raised = raised_types(fn)
        declared = {e.split()[0] for e in tags.get("raises", []) if e.split()}
        if raised - declared:
            errors.append(f"{loc}: raises {sorted(raised - declared)} not in @raises")
        for flag in (e.split()[0] for e in tags.get("flag", []) if e.split()):
            if flag not in known_flags:
                errors.append(f"{loc}: @flag {flag!r} is not defined in flags.yml")
    return errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.environ.get("GITHUB_WORKSPACE") or ".")
    ap.add_argument("--src", default=None)
    ap.add_argument("--flags", default=None)
    args = ap.parse_args()

    root = Path(args.root).resolve()
    src_root = Path(args.src).resolve() if args.src else root / "src"
    flags_path = Path(args.flags).resolve() if args.flags else root / "flags.yml"
    known_flags = set(load_flags(flags_path))

    errors: list[str] = []
    files = sorted(src_root.rglob("*.py"))
    for f in files:
        errors.extend(check_file(f, root, known_flags))

    if errors:
        print("Metadata contract check FAILED:\n")
        for e in errors:
            print(f"  ✗ {e}")
        print(f"\n{len(errors)} problem(s). Stale metadata is a build failure.")
        return 1
    print(f"Metadata contract check passed ✓  ({len(files)} file(s), {len(known_flags)} flag(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
