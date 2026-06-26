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
import re
import subprocess
from pathlib import Path

from context_resolver import contracts_path, glossary_path, resolve_context
from contract_lib import (
    _FILLER,
    _FILLER_STEMS,
    _stem,
    _words,
    collect_contracts,
    documented_params,
    is_low_signal_intent,
    is_sediment_intent,
    parse_tags,
    raised_types,
    returns_value,
    signature_params,
)
from contracts_registry import load_contracts
from extract import git_changed_paths
from flags_registry import load_flags


DEFAULT_TAGS: dict[str, dict] = {
    "intent": {"required": "true"},
    "param": {"required": "auto"},
    "returns": {"required": "auto"},
    "raises": {"required": "false"},
    "feature": {"required": "false"},
    "flag": {"required": "false"},
}


_HEADING_RE = re.compile(r"^#{1,4}\s+(.+)$")
_TERM_WORD_RE = re.compile(r"[A-Za-z]+")


def _load_glossary_terms(path: Path) -> set[tuple[str, ...]]:
    """Return normalized (stemmed, lowercased) term token tuples from a CONTEXT.md.

    Terms are taken from markdown headings. A heading like ``### ShipWindow`` or
    ``### Line item`` becomes a set of tokens used to decide whether an @intent
    word is already defined in the context's glossary.
    """
    if not path.exists():
        return set()
    terms: set[tuple[str, ...]] = set()
    for raw in path.read_text().splitlines():
        line = raw.strip()
        m = _HEADING_RE.match(line)
        if not m:
            continue
        title = m.group(1).strip()
        # Strip inline markdown decoration; domain terms rarely contain it.
        title = re.sub(r"[*`\[\]]", "", title)
        tokens = tuple(_stem(w) for w in _words(title) if w)
        if not tokens:
            continue
        terms.add(tokens)
    return terms


def _is_term_candidate(word: str) -> bool:
    """True for a likely domain term in @intent prose.

    Filters out short words, plain filler, and all-lowercase words (which are
    usually grammar, not ubiquitous-language concepts).
    """
    if len(word) <= 1:
        return False
    if not any(c.isupper() for c in word):
        return False
    low = word.lower()
    if low in _FILLER or _stem(low) in _FILLER_STEMS:
        return False
    return True


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
    qualnames (the diff-scoped path); ``None`` gates all of them (full mode).
    The context is resolved per file so the correct contracts.yml drives tag
    validation."""
    errors: list[str] = []
    tree = ast.parse(path.read_text(), filename=str(path))
    funcs = _funcs(tree)

    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = path

    context = resolve_context(path, root)
    contracts = load_contracts(contracts_path(root, context))
    if not contracts:
        contracts = DEFAULT_TAGS

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

        # Validate that every used @tag is declared in this context's contracts.
        for tag_name in tags:
            if tag_name not in contracts:
                errors.append(f"{loc}: @{tag_name} is not a valid tag in context '{context}'")

        # Context-aware required checks per contracts.yml (true/false/auto).
        # When a contracts.yml is present, it fully replaces the default tag set;
        # legacy hardcoded @param/@returns checks only run on the fallback path.
        sig, documented = signature_params(fn), documented_params(tags)
        for tag_name, spec in contracts.items():
            required = spec.get("required", "false")
            if required == "true" and not tags.get(tag_name):
                errors.append(f"{loc}: missing required @{tag_name} (context: {context})")
            elif required == "auto":
                if tag_name == "param" and sig - documented:
                    errors.append(f"{loc}: @param missing for {sorted(sig - documented)}")
                if tag_name == "returns" and returns_value(fn) and not tags.get("returns"):
                    errors.append(f"{loc}: returns a value but has no @returns")

        raised = raised_types(fn)
        declared = {e.split()[0] for e in tags.get("raises", []) if e.split()}
        if raised - declared:
            errors.append(f"{loc}: raises {sorted(raised - declared)} not in @raises")
        for flag in (e.split()[0] for e in tags.get("flag", []) if e.split()):
            if flag not in known_flags:
                errors.append(f"{loc}: @flag {flag!r} is not defined in flags.yml")
    return errors


def glossary_terms(path: Path, root: Path) -> list[str]:
    """Advisory glossary check: propose domain terms used in @intent but not yet
    defined in the nearest CONTEXT.md. Returns proposal strings, never failures."""
    context = resolve_context(path, root)
    terms = _load_glossary_terms(glossary_path(root, context))
    if not terms:
        return []

    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = path

    proposals: list[str] = []
    tree = ast.parse(path.read_text(), filename=str(path))
    for fn, qual in _funcs(tree):
        if fn.name.startswith("_"):
            continue
        doc = ast.get_docstring(fn)
        if not doc:
            continue
        tags = parse_tags(doc)
        intent = " ".join(tags.get("intent", [])).strip()
        if not intent:
            continue
        seen: set[str] = set()
        for m in _TERM_WORD_RE.finditer(intent):
            word = m.group(0)
            if not _is_term_candidate(word):
                continue
            normalized = tuple(_stem(w) for w in _words(word) if w)
            if not normalized or normalized in terms:
                continue
            if word in seen:
                continue
            seen.add(word)
            loc = f"{rel}:{fn.lineno}"
            proposals.append(f"Proposed glossary term: {word} (in {loc})")
    return proposals


def _print_glossary_report(proposals: list[str]) -> None:
    if not proposals:
        return
    print("\nGlossary check — @intent uses terms not yet in CONTEXT.md. Ratify or reject at review:\n")
    for p in proposals:
        print(f"  ⚠ {p}")
    print(f"\n{len(proposals)} proposed term(s). Advisory — not a build break.")


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


def sediment_report(root: Path, src_root: Path, fail: bool) -> int:
    """Advisory no-op lint: flag @intent that merely restates the symbol name (sediment).
    The deterministic pre-filter for /ratify — meaning has to be recovered, not rubber-stamped."""
    contracts = collect_contracts(src_root, root)
    flagged = [c for c in contracts if c.intent and is_sediment_intent(c.name, c.intent)]
    if not flagged:
        print(f"No-op lint: no sediment ✓  ({len(contracts)} contract(s) scanned)")
        return 0
    print("No-op lint — @intent restates the name (sediment). Recover real meaning via /ratify:\n")
    for c in flagged:
        print(f'  ⚠ {c.loc}: @intent "{c.intent}" adds nothing over `{c.name}`')
    tail = "Failing (--fail-on-sediment)." if fail else "Advisory — not a build break."
    print(f"\n{len(flagged)} sediment of {len(contracts)} scanned. {tail}")
    return 1 if fail else 0


def signal_report(root: Path, src_root: Path, fail: bool) -> int:
    """Advisory signal lint: flag @intent that contains no domain terms from the
    context's CONTEXT.md glossary. Vague prose like 'handles the request' is a
    candidate for re-ratification; it does not break the build."""
    contracts = collect_contracts(src_root, root)
    flagged: list[FunctionContract] = []
    for c in contracts:
        if not c.intent:
            continue
        context = resolve_context(root / c.rel_path, root)
        terms = _load_glossary_terms(glossary_path(root, context))
        if not terms:
            continue  # no glossary → no signal check for this context
        if is_low_signal_intent(c.intent, terms):
            flagged.append(c)
    if not flagged:
        print(f"Signal lint: all intents carry domain terms ✓  ({len(contracts)} contract(s) scanned)")
        return 0
    print("Signal lint — @intent is too vague (no glossary domain terms). Add bounded-context meaning:\n")
    for c in flagged:
        print(f'  ⚠ {c.loc}: @intent "{c.intent}" adds no domain term')
    tail = "Failing (--fail-on-low-signal)." if fail else "Advisory — not a build break."
    print(f"\n{len(flagged)} low-signal of {len(contracts)} scanned. {tail}")
    return 1 if fail else 0

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.environ.get("GITHUB_WORKSPACE") or ".")
    ap.add_argument("--src", default=None)
    ap.add_argument("--flags", default=None)
    ap.add_argument("--no-op-lint", action="store_true",
                    help="advisory: flag @intent that merely restates the name (sediment)")
    ap.add_argument("--fail-on-sediment", action="store_true",
                    help="with --no-op-lint, exit non-zero on findings")
    ap.add_argument("--signal-lint", action="store_true",
                    help="advisory: flag @intent that contains no domain terms from the glossary")
    ap.add_argument("--fail-on-low-signal", action="store_true",
                    help="with --signal-lint, exit non-zero on findings")
    ap.add_argument("--since", default=None,
                    help="boy-scout mode: gate only functions changed since this git ref")
    ap.add_argument("--changed", action="append", default=None,
                    help="boy-scout mode: gate only changed functions in this path (repeatable)")
    ap.add_argument("--include-working", action="store_true",
                    help="with --since/--changed, also include unstaged + staged edits")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    src_root = Path(args.src).resolve() if args.src else root / "src"

    if args.no_op_lint:
        return sediment_report(root, src_root, args.fail_on_sediment)

    if args.signal_lint:
        return signal_report(root, src_root, args.fail_on_low_signal)

    flags_path = Path(args.flags).resolve() if args.flags else root / "flags.yml"
    known_flags = set(load_flags(flags_path))

    scoped = bool(args.since or args.changed or args.include_working)
    proposal_files: list[Path] = []
    if scoped:
        changed, _deleted = git_changed_paths(root, args.since, args.include_working)
        if args.changed:
            changed |= set(args.changed)
        proposal_files = [root / rel for rel in sorted(changed)
                          if rel.endswith(".py") and (root / rel).exists()
                          and _under(root / rel, src_root)]
        errors = scoped_check(root, src_root, known_flags, args.since, args.include_working,
                              changed=set(args.changed) if args.changed else None)
        scope_desc = f"diff-scoped (since {args.since or 'HEAD'})"
    else:
        proposal_files = sorted(src_root.rglob("*.py"))
        errors = []
        for f in proposal_files:
            errors.extend(check_file(f, root, known_flags))
        scope_desc = f"{len(proposal_files)} file(s)"

    proposals: list[str] = []
    for f in proposal_files:
        proposals.extend(glossary_terms(f, root))

    if errors:
        print("Metadata contract check FAILED:\n")
        for e in errors:
            print(f"  ✗ {e}")
        print(f"\n{len(errors)} problem(s). Stale metadata is a build failure.")
        if proposals:
            _print_glossary_report(proposals)
        return 1
    print(f"Metadata contract check passed ✓  ({scope_desc}, {len(known_flags)} flag(s))")
    _print_glossary_report(proposals)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())