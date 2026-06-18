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
from pathlib import Path

from contract_lib import (
    documented_params,
    parse_tags,
    raised_types,
    returns_value,
    signature_params,
)
from flags_registry import load_flags


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