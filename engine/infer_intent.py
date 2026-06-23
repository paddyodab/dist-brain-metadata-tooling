#!/usr/bin/env python3
"""Infer draft @intent contracts for legacy code (v0 — no LLM).

Triangulates: public API surface, lexical raises/returns, git log near scope,
test name mentions, and call-site imports. Output is a ratification queue —
inference is draft, not truth.

Usage:
  python3 infer_intent.py --root ../sandbox --path app/services/articles.py
  python3 infer_intent.py --root . --path app/services --since 2020-01-01
  python3 infer_intent.py --root . --path app/services/articles.py --out inference-queue.md
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

STOPWORDS = frozenset(
    "a an and as at be by for from in into is it of on or the to with".split()
)


@dataclass
class Symbol:
    rel_path: str
    qualname: str
    kind: str
    lineno: int
    params: list[str]
    returns: str | None
    raises: list[str]
    has_intent: bool
    fn_segment: str = ""
    callers: list[str] = field(default_factory=list)
    test_hints: list[str] = field(default_factory=list)
    commit_hints: list[str] = field(default_factory=list)


def _run_git(root: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


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


def raised_types(fn) -> list[str]:
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
    return sorted(types)


def parse_tags(docstring: str) -> dict[str, list[str]]:
    tags: dict[str, list[str]] = {}
    current = None
    buffer: list[str] = []
    tag_re = re.compile(r"@(\w+)\b")

    def flush() -> None:
        nonlocal buffer
        if current is not None:
            tags.setdefault(current, []).append(" ".join(buffer).strip())
        buffer = []

    for raw in docstring.splitlines():
        line = raw.strip()
        m = tag_re.match(line)
        if m:
            flush()
            current = m.group(1)
            buffer = [line[m.end():].strip()]
        elif current is not None:
            buffer.append(line)
    flush()
    return tags


def collect_symbols(path: Path, root: Path) -> list[Symbol]:
    source = path.read_text()
    tree = ast.parse(source, filename=str(path))
    rel = path.relative_to(root).as_posix()
    out: list[Symbol] = []

    def handle(fn, qual: str, kind: str) -> None:
        if fn.name.startswith("_"):
            return
        doc = ast.get_docstring(fn) or ""
        tags = parse_tags(doc) if doc else {}
        intent = (tags.get("intent") or [""])[0]
        segment = ast.get_source_segment(source, fn) or ""
        out.append(Symbol(
            rel_path=rel,
            qualname=qual,
            kind=kind,
            lineno=fn.lineno,
            params=signature_params(fn),
            returns=returns_type(fn),
            raises=raised_types(fn),
            has_intent=bool(intent.strip()),
            fn_segment=segment,
        ))

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            handle(node, node.name, "function")
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    handle(sub, f"{node.name}.{sub.name}", "method")
    return out


def scope_files(root: Path, src_root: Path, path_arg: str) -> list[Path]:
    target = (root / path_arg).resolve()
    if not target.exists():
        raise SystemExit(f"path not found: {target}")
    if target.is_file():
        return [target]
    return sorted(p for p in target.rglob("*.py") if p.name != "__init__.py")


def git_commits(root: Path, rel_path: str, since: str | None) -> list[str]:
    args = ["log", "--format=%h %s", "--follow", "--", rel_path]
    if since:
        args[1:1] = [f"--since={since}"]
    lines = [ln.strip() for ln in _run_git(root, *args).splitlines() if ln.strip()]
    return lines[:20]


def find_callers(root: Path, src_root: Path, name: str, exclude_rel: str) -> list[str]:
    callers: list[str] = []
    for py in src_root.rglob("*.py"):
        if py.name == "__init__.py":
            continue
        rel = py.relative_to(root).as_posix()
        if rel == exclude_rel:
            continue
        text = py.read_text()
        if re.search(rf"\b{re.escape(name)}\s*\(", text):
            callers.append(rel)
    return sorted(set(callers))[:8]


def find_test_hints(root: Path, name: str) -> list[str]:
    hints: list[str] = []
    tests = root / "tests"
    if not tests.exists():
        return hints
    for py in tests.rglob("*.py"):
        for i, line in enumerate(py.read_text().splitlines(), 1):
            if name in line and ("def test_" in line or "async def test_" in line):
                hints.append(f"{py.relative_to(root).as_posix()}:{i} {line.strip()[:80]}")
    if not hints:
        for py in tests.rglob("test_*.py"):
            text = py.read_text()
            if name in text:
                hints.append(py.relative_to(root).as_posix())
    return hints[:6]


def keyword_themes(commits: list[str]) -> list[str]:
    words: dict[str, int] = {}
    for line in commits:
        msg = line.split(" ", 1)[-1].lower()
        for tok in re.findall(r"[a-z][a-z0-9_-]{2,}", msg):
            if tok not in STOPWORDS:
                words[tok] = words.get(tok, 0) + 1
    return [w for w, _ in sorted(words.items(), key=lambda x: (-x[1], x[0]))[:8]]


def draft_intent(sym: Symbol, source: str, fn_segment: str) -> str:
    name = sym.qualname.split(".")[-1]
    parts: list[str] = []

    if sym.returns == "bool" or name.startswith("check_") or name.startswith("is_"):
        parts.append("Predicate helper")
    elif sym.returns == "str" or name.startswith("get_"):
        parts.append("Derives or returns a value")
    else:
        parts.append("Service helper")

    if "slug" in name or "slug" in sym.params:
        parts.append("for article URL slugs")
    if "article" in name:
        parts.append("in the article lifecycle")
    if "user" in sym.params or "modify" in name:
        parts.append("enforcing author-only mutation")
    if sym.raises:
        parts.append(f"may raise {', '.join(sym.raises)}")
    elif sym.returns == "bool" and "EntityDoesNotExist" in fn_segment:
        parts.append("maps missing entities to False instead of raising")
    if "slugify" in source and "slug" in name and "get_slug" in name:
        parts.append("via slugify on title")

    if sym.callers:
        parts.append(f"used from {sym.callers[0]}")
    if sym.test_hints:
        parts.append("behavior covered in tests")

    text = "; ".join(parts)
    if not text.endswith("."):
        text += "."
    return text[0].upper() + text[1:]


def render_queue(
    root: Path,
    symbols: list[Symbol],
    path_arg: str,
    since: str | None,
    sources: dict[str, str],
) -> str:
    sha = _run_git(root, "rev-parse", "--short", "HEAD").strip() or "nogit"
    stamp = datetime.now().isoformat(timespec="seconds")
    missing = [s for s in symbols if not s.has_intent]
    lines = [
        "# Inference queue (draft — ratify before gate)",
        "",
        f"_Generated by `infer_intent.py` @ `{sha}` · {stamp}_",
        f"_Scope: `{path_arg}` · symbols without `@intent`: {len(missing)}_",
        "",
        "Approve, edit, or reject each draft. Approved → add `@intent` + `@provenance inferred`",
        "to the docstring, then flip to `verified` after review.",
        "",
    ]
    if not missing:
        lines.append("_No symbols missing `@intent` in scope._")
        return "\n".join(lines) + "\n"

    by_file: dict[str, list[Symbol]] = {}
    for sym in missing:
        by_file.setdefault(sym.rel_path, []).append(sym)

    for rel, syms in sorted(by_file.items()):
        commits = git_commits(root, rel, since)
        themes = keyword_themes(commits)
        lines.extend([
            f"## `{rel}`",
            "",
            "**Git themes:** " + (", ".join(themes) if themes else "—"),
            "",
        ])
        if commits:
            lines.append("**Recent commits:**")
            for c in commits[:6]:
                lines.append(f"- {c}")
            lines.append("")

        for sym in syms:
            entity_id = f"{sym.rel_path}#{sym.qualname}"
            lines.extend([
                f"### `{entity_id}`",
                "",
                f"- **Line:** {sym.lineno}",
                f"- **Signature:** `({', '.join(sym.params)})` → `{sym.returns or 'None'}`",
                f"- **Lexical raises:** {', '.join(sym.raises) if sym.raises else '—'}",
                f"- **Callers:** {', '.join(f'`{c}`' for c in sym.callers) or '—'}",
                f"- **Tests:** {', '.join(f'`{t}`' for t in sym.test_hints) or '—'}",
                "",
                "**Draft contract:**",
                "",
                "```python",
                f'"""',
                f"@intent {draft_intent(sym, sources.get(sym.rel_path, ''), sym.fn_segment)}",
                "@provenance status: inferred",
                f"@provenance inferred_by: infer_intent@0",
                f"@provenance inferred_at: {stamp}",
            ])
            for p in sym.params:
                lines.append(f"@param {p}")
            if sym.returns and sym.returns != "<value>":
                lines.append(f"@returns {sym.returns}")
            for exc in sym.raises:
                lines.append(f"@raises {exc}")
            lines.extend(['"""', "```", ""])
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Infer draft @intent for legacy symbols (v0)")
    ap.add_argument("--root", default=".", help="consumer repo root")
    ap.add_argument("--src", default="app", help="source tree (default: app for RealWorld)")
    ap.add_argument("--path", required=True, help="file or directory under --root")
    ap.add_argument("--since", default=None, help="git --since for commit archaeology")
    ap.add_argument("--out", default="inference-queue.md", help="output markdown path")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    src_root = (root / args.src).resolve()
    if not src_root.is_dir():
        raise SystemExit(f"--src not found: {src_root}")

    symbols: list[Symbol] = []
    sources: dict[str, str] = {}
    for path in scope_files(root, src_root, args.path):
        sources[path.relative_to(root).as_posix()] = path.read_text()
        for sym in collect_symbols(path, root):
            sym.commit_hints = git_commits(root, sym.rel_path, args.since)
            sym.callers = find_callers(
                root, src_root, sym.qualname.split(".")[-1], sym.rel_path,
            )
            sym.test_hints = find_test_hints(root, sym.qualname.split(".")[-1])
            symbols.append(sym)

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = root / out_path
    text = render_queue(root, symbols, args.path, args.since, sources)
    out_path.write_text(text)

    missing = sum(1 for s in symbols if not s.has_intent)
    print(f"infer_intent @ {_run_git(root, 'rev-parse', '--short', 'HEAD').strip() or 'nogit'}")
    print(f"  · scope: {args.path}")
    print(f"  · symbols: {len(symbols)} ({missing} missing @intent)")
    print(f"  → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())