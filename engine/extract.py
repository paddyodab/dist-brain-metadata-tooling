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
import subprocess
from pathlib import Path

from context_resolver import resolve_context
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
    context = resolve_context(path, root)

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
            "context": context,
        })
        for exc in raises:
            edges.append({"from": node_id, "to": f"exception:{exc}", "type": "raises", "origin": "derived"})
        if flag:
            edges.append({"from": node_id, "to": f"flag:{flag}", "type": "gated-by", "origin": "authored"})
        for adapts in tags.get("adapts", []):
            target = adapts.split()[0] if adapts.split() else ""
            if target:
                edges.append({"from": node_id, "to": target, "type": "adapts", "origin": "authored"})

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            handle(node, node.name, "function")
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    handle(sub, f"{node.name}.{sub.name}", "method")
    return nodes, edges


def adr_summary(text: str) -> str:
    """First paragraph under '## Decision', else the first paragraph after the title."""
    lines = text.splitlines()
    for marker in ("## Decision", "##Decision"):
        if marker in text:
            i = next(k for k, l in enumerate(lines) if l.strip().startswith(marker))
            para: list[str] = []
            for l in lines[i + 1:]:
                if l.strip().startswith("#"):
                    break
                if l.strip():
                    para.append(l.strip())
                elif para:
                    break
            if para:
                return " ".join(para)
    for l in lines:
        s = l.strip()
        if s and not s.startswith("#") and not s.startswith("**Status"):
            return s
    return ""


def adr_nodes(root: Path) -> list[dict]:
    """Ingest decisions/*.md (ADRs) as decision nodes — the cross-cutting 'why'.

    Pure Nygard: no frontmatter parsing, no constraint machinery. The title comes from
    the first ``# `` line; status comes from ``**Status:**``. Records only — all
    forward-looking, enforceable rules live in ``house-rules/*.yml``.
    """
    d = root / "decisions"
    out: list[dict] = []
    if not d.exists():
        return out
    for f in sorted(d.glob("*.md")):
        raw = f.read_text()
        lines = raw.splitlines()
        title = next((l[2:].strip() for l in lines if l.startswith("# ")), f.stem)
        status = next(
            (l.split("**Status:**", 1)[1].strip()
             for l in lines if "**Status:**" in l), None)
        context = resolve_context(f, root)
        out.append({
            "id": f"decision:{f.stem}", "type": "decision", "title": title,
            "intent": adr_summary(raw),
            "facts": {"status": status, "kind": "record"},
            "subsystem": "decisions",
            "provenance": {"source_path": str(f.relative_to(root)),
                           "source_sha": hashlib.sha1(raw.encode()).hexdigest()[:12],
                           "status": "verified", "extracted_by": "adr@1"},
            "context": context,
        })
    return out


def _parse_yml_value(val: str) -> str:
    """Strip surrounding quotes and trailing whitespace from a flat YAML scalar."""
    return val.strip().strip('"').strip("'")


def _parse_house_rule(raw: str) -> dict | None:
    """Stdlib-only parser for flat house-rules/*.yml.

    Recognized fields: id, rule, rationale (string or | block), enforcement, gate,
    applies_to, status. Block scalars (|) collect every subsequent indented line.
    Returns None if the file is empty or has no rule.
    """
    if not raw.strip():
        return None
    lines = raw.splitlines()
    fields: dict[str, str | None] = {
        "id": None, "rule": None, "rationale": None, "enforcement": "advisory",
        "gate": None, "applies_to": None, "status": None,
    }
    current: str | None = None
    buffer: list[str] = []
    block_key_indent: int | None = None

    def flush() -> None:
        if current is not None and current in fields:
            fields[current] = "\n".join(buffer).strip()

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        line_indent = len(line) - len(line.lstrip())
        # Block-scalar continuation: any line more indented than the key that opened
        # the block belongs to that field, even if it looks like a top-level key.
        if current is not None and block_key_indent is not None and line_indent > block_key_indent:
            content_indent = block_key_indent + 2
            buffer.append(line[content_indent:] if len(line) >= content_indent else line.lstrip())
            continue
        flush()
        key, sep, val = line.partition(":")
        if not sep:
            continue
        key = key.strip().lower()
        val = val.strip()
        current = key
        if val == "|":
            buffer = []
            block_key_indent = line_indent
        else:
            buffer = [_parse_yml_value(val)]
            block_key_indent = None
    flush()
    return fields if fields["rule"] else None


def house_rules_nodes(root: Path) -> list[dict]:
    """Ingest house-rules/*.yml as 'house-rule' nodes — the enforceable premises.

    Machine-readable, forward-looking constraints. Each rule has an enforcement level
    (advisory, semantic, deterministic) and an optional gate script for deterministic
    enforcement. Status controls whether the rule is active (only 'accepted' is enforced).
    """
    d = root / "house-rules"
    out: list[dict] = []
    if not d.exists():
        return out
    for f in sorted(d.glob("*.yml")):
        raw = f.read_text()
        parsed = _parse_house_rule(raw)
        if parsed is None:
            continue
        facts: dict = {
            "status": parsed["status"],
            "enforcement": (parsed["enforcement"] or "advisory").lower(),
        }
        for k in ("gate", "applies_to"):
            if parsed.get(k):
                facts[k] = parsed[k]
        if parsed.get("id"):
            facts["rule_id"] = parsed["id"]
        out.append({
            "id": f"house-rule:{f.stem}", "type": "house-rule", "title": parsed["rule"],
            "intent": parsed["rationale"],
            "facts": facts,
            "subsystem": "house-rules",
            "provenance": {"source_path": str(f.relative_to(root)),
                           "source_sha": hashlib.sha1(raw.encode()).hexdigest()[:12],
                           "status": "verified", "extracted_by": "house-rules@1"},
        })
    return out


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


def _is_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def git_changed_paths(root: Path, since: str | None,
                      include_working: bool) -> tuple[set[str], set[str]]:
    """Return (changed, deleted) repo-relative paths from git.

    `since` diffs ``<since>..HEAD``; `include_working` adds unstaged + staged edits.
    Coarse filter only — per-function ``source_sha`` decides actual node changes.
    """
    changed: set[str] = set()
    deleted: set[str] = set()

    def run(*args: str) -> list[str]:
        try:
            out = subprocess.run(["git", "-C", str(root), *args],
                                 capture_output=True, text=True, check=True).stdout
            return out.splitlines()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return []

    specs: list[list[str]] = []
    if since:
        specs.append(["diff", "--name-status", f"{since}..HEAD"])
    if include_working:
        specs.append(["diff", "--name-status", "HEAD"])      # unstaged
        specs.append(["diff", "--name-status", "--cached"])  # staged

    for spec in specs:
        for line in run(*spec):
            if not line.strip():
                continue
            status, _, path = line.partition("\t")
            path = path.strip()
            # renames look like "R100\told\tnew"; take the destination
            if status.startswith("R") and "\t" in path:
                path = path.split("\t")[-1].strip()
            (deleted if status.startswith("D") else changed).add(path)
    return changed, deleted


def extract_full(root: Path, src_root: Path, flags_path: Path) -> dict:
    nodes = list(flag_nodes(flags_path)) + adr_nodes(root) + house_rules_nodes(root)
    edges: list[dict] = []
    for f in sorted(src_root.rglob("*.py")):
        n, e = extract_file(f, root)
        nodes.extend(n)
        edges.extend(e)
    return {"nodes": nodes, "edges": edges, "scope": None}


def extract_scoped(root: Path, src_root: Path, flags_path: Path,
                   changed: set[str], deleted: set[str]) -> dict:
    """Re-extract only in-scope files. The ``scope`` block tells the consumer which
    source paths are authoritative this run (only those may have nodes removed)."""
    nodes: list[dict] = []
    edges: list[dict] = []
    touched = changed | deleted

    # small categories are cheap — re-extract wholesale if their file is in scope
    if any(Path(p).name == flags_path.name for p in touched):
        nodes += flag_nodes(flags_path)
    if any(p.startswith("decisions/") for p in touched):
        nodes += adr_nodes(root)
    if any(p.startswith("house-rules/") for p in touched):
        nodes += house_rules_nodes(root)

    for p in sorted(changed):
        f = (root / p)
        if not p.endswith(".py") or not f.exists() or not _is_under(f, src_root):
            continue
        n, e = extract_file(f, root)
        nodes.extend(n)
        edges.extend(e)

    return {
        "nodes": nodes,
        "edges": edges,
        "scope": {"paths": sorted(changed), "deleted": sorted(deleted)},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.environ.get("GITHUB_WORKSPACE") or ".")
    ap.add_argument("--src", default=None)
    ap.add_argument("--flags", default=None)
    ap.add_argument("--since", default=None,
                    help="only re-extract files changed since this git ref (diff <ref>..HEAD)")
    ap.add_argument("--changed", action="append", default=None,
                    help="only re-extract this repo-relative path (repeatable)")
    ap.add_argument("--include-working", action="store_true",
                    help="with --since/--changed, also include unstaged + staged edits")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    src_root = Path(args.src).resolve() if args.src else root / "src"
    flags_path = Path(args.flags).resolve() if args.flags else root / "flags.yml"

    scoped = bool(args.since or args.changed or args.include_working)
    if not scoped:
        result = extract_full(root, src_root, flags_path)
    else:
        if args.changed:
            changed, deleted = set(args.changed), set()
        else:
            changed, deleted = git_changed_paths(root, args.since, args.include_working)
        result = extract_scoped(root, src_root, flags_path, changed, deleted)

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
