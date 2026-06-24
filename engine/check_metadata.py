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
                                 [--since REF] [--changed PATH ...] [--include-working]

Default: gate every public function under --src. With --since/--changed (the boy-scout
path), gate only the public functions a diff actually added or changed — unchanged
siblings in a touched file are left alone, so legacy debt isn't force-marched on every PR.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import os
import subprocess
from pathlib import Path

from contract_lib import (
    documented_params,
    parse_tags,
    raised_types,
    returns_value,
    signature_params,
)
from extract import git_changed_paths
from flags_registry import load_flags


def _funcs(tree: ast.AST) -> list[tuple[ast.AST, str]]:
    out: list[tuple[ast.AST, str]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append((node, node.name))
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out.append((sub, f"{node.name}.{sub.name}"))
    return out


def check_file(path: Path, root: Path, known_flags: set[str],
               only: set[str] | None = None) -> list[str]:
    """Gate public functions in ``path``. If ``only`` is given, restrict to those
    qualnames (the diff-scoped path); ``None`` gates all of them (full mode)."""
    errors: list[str] = []
    tree = ast.parse(path.read_text(), filename=str(path))
    funcs = _funcs(tree)

    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = path
    for fn, qual in funcs:
        if fn.name.startswith("_"):
            continue
        if only is not None and qual not in only:
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


def _under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _segment_shas(source: str) -> dict[str, str]:
    """qualname -> sha of its source segment, for one file version. Same fine filter
    used by extract: a function counts as changed iff its own segment changed."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    out: dict[str, str] = {}
    for fn, qual in _funcs(tree):
        if fn.name.startswith("_"):
            continue
        seg = ast.get_source_segment(source, fn) or ""
        out[qual] = hashlib.sha1(seg.encode()).hexdigest()[:12]
    return out


def changed_quals(root: Path, rel: str, base_ref: str) -> set[str]:
    """Public qualnames in ``rel`` that are new or whose source changed vs ``base_ref``.
    A file absent at base (new file) yields all of its public qualnames."""
    head = _segment_shas((root / rel).read_text())
    base_src = subprocess.run(["git", "-C", str(root), "show", f"{base_ref}:{rel}"],
                              capture_output=True, text=True).stdout
    base = _segment_shas(base_src) if base_src else {}
    return {q for q, sha in head.items() if base.get(q) != sha}


def scoped_check(root: Path, src_root: Path, known_flags: set[str],
                 since: str | None, include_working: bool,
                 changed: set[str] | None = None) -> list[str]:
    """Gate only the public functions a diff added/changed. ``base_ref`` is ``since``
    (the committed diff base), or HEAD when only working-tree edits are in scope."""
    base_ref = since or "HEAD"
    if changed is None:
        changed, _deleted = git_changed_paths(root, since, include_working)
    errors: list[str] = []
    for rel in sorted(changed):
        f = root / rel
        if not rel.endswith(".py") or not f.exists() or not _under(f, src_root):
            continue
        quals = changed_quals(root, rel, base_ref)
        if quals:
            errors.extend(check_file(f, root, known_flags, only=quals))
    return errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.environ.get("GITHUB_WORKSPACE") or ".")
    ap.add_argument("--src", default=None)
    ap.add_argument("--flags", default=None)
    ap.add_argument("--since", default=None,
                    help="boy-scout mode: gate only functions changed since this git ref")
    ap.add_argument("--changed", action="append", default=None,
                    help="boy-scout mode: gate only changed functions in this path (repeatable)")
    ap.add_argument("--include-working", action="store_true",
                    help="with --since/--changed, also include unstaged + staged edits")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    src_root = Path(args.src).resolve() if args.src else root / "src"
    flags_path = Path(args.flags).resolve() if args.flags else root / "flags.yml"
    known_flags = set(load_flags(flags_path))

    scoped = bool(args.since or args.changed or args.include_working)
    if scoped:
        errors = scoped_check(root, src_root, known_flags, args.since, args.include_working,
                              changed=set(args.changed) if args.changed else None)
        scope_desc = f"diff-scoped (since {args.since or 'HEAD'})"
    else:
        errors = []
        files = sorted(src_root.rglob("*.py"))
        for f in files:
            errors.extend(check_file(f, root, known_flags))
        scope_desc = f"{len(files)} file(s)"

    if errors:
        print("Metadata contract check FAILED:\n")
        for e in errors:
            print(f"  ✗ {e}")
        print(f"\n{len(errors)} problem(s). Stale metadata is a build failure.")
        return 1
    print(f"Metadata contract check passed ✓  ({scope_desc}, {len(known_flags)} flag(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())