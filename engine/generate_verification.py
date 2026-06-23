#!/usr/bin/env python3
"""Generate pytest verification stubs from colocated @intent/@raises contracts.

Contracts are the spec; these tests are the executable verification layer that
lets agents (and long-running sessions) know when they're done.

Usage:
  python3 generate_verification.py --root ../my-app-with-a-wiki-01
  python3 generate_verification.py --root . --check   # CI: fail if stubs are stale

Regenerate after contract changes, then implement any new stubs until pytest passes.
"""
from __future__ import annotations

import argparse
import os
import textwrap
from pathlib import Path

from contract_lib import FunctionContract, collect_contracts, module_import_path

HEADER = '''\
"""Contract verification tests — generated from colocated metadata.

Do not edit the STRUCTURE by hand. Change the @intent/@raises contract or run:
  python3 {regen_cmd}

These tests are the verification checkpoint for /feature and long-running agents:
if contracts say it, a test must prove it.

Unimplemented stubs call pytest.skip (not fail) so legacy repos can run the app
test suite while ratifying incrementally. Implement the body → skip disappears.
"""
# fmt: off — generated file
import pytest

pytestmark = pytest.mark.contract_verification

{imports}

'''


def _slug(s: str) -> str:
    out = []
    for ch in s:
        out.append(ch if ch.isalnum() else "_")
    slug = "".join(out).strip("_").lower()
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "fn"


def _render_imports(contracts: list[FunctionContract], src_root: Path, root: Path) -> str:
    exc_mod: str | None = None
    for path in src_root.rglob("*.py"):
        text = path.read_text()
        if "class LinkNotFound" in text or "class InvalidURL" in text:
            try:
                rel = path.relative_to(root)
            except ValueError:
                rel = path.relative_to(src_root)
            exc_mod = module_import_path(rel)
            break
    raises = sorted({e for c in contracts for e in c.raises})
    lines = []
    if exc_mod and raises:
        names = sorted(set(raises) | {"LinkStore"})
        lines.append(f"from {exc_mod} import {', '.join(names)}")
    by_mod: dict[str, list[str]] = {}
    for c in contracts:
        by_mod.setdefault(c.module, []).append(c.name)
    for mod in sorted(by_mod):
        names = sorted(set(by_mod[mod]))
        lines.append(f"from {mod} import {', '.join(names)}")
    return "\n".join(lines)


def _stub_body(c: FunctionContract, exc: str, store: str) -> str:
    """Best-effort executable stub from contract shape (not LLM guesswork)."""
    call = c.name
    if exc == "InvalidURL" and "url" in c.params:
        return textwrap.dedent(f"""\
            s = {store}()
            with pytest.raises(InvalidURL):
                {call}(s, "ftp://nope")
        """)
    if exc == "AliasTaken" and "alias" in c.params:
        return textwrap.dedent(f"""\
            s = {store}()
            {call}(s, "https://a.com", alias="aa")
            with pytest.raises(AliasTaken):
                {call}(s, "https://b.com", alias="aa")
        """)
    if exc == "LinkNotFound" and "code" in c.params:
        return textwrap.dedent(f"""\
            s = {store}()
            with pytest.raises(LinkNotFound):
                {call}(s, "zzz")
        """)
    return textwrap.dedent(f"""\
        pytest.skip(
            "Implement contract verification for {c.entity_id} @raises {exc}"
        )
    """)


def _returns_smoke(c: FunctionContract, store: str, contracts: list[FunctionContract]) -> str | None:
    if not c.returns:
        return None
    create_fn = "create_short_link" if any(x.name == "create_short_link" for x in contracts) else None
    if c.name == "create_short_link" and "url" in c.params:
        return textwrap.dedent(f"""\
            s = {store}()
            link = {c.name}(s, "https://example.com")
            assert link.url == "https://example.com"
            assert link.code
        """)
    if c.name == "resolve" and create_fn:
        return textwrap.dedent(f"""\
            s = {store}()
            link = {create_fn}(s, "https://example.com")
            assert {c.name}(s, link.code) == "https://example.com"
        """)
    if c.name == "record_click" and create_fn:
        return textwrap.dedent(f"""\
            s = {store}()
            link = {create_fn}(s, "https://x.com")
            assert {c.name}(s, link.code) == 1
        """)
    if c.name == "click_count" and create_fn:
        return textwrap.dedent(f"""\
            s = {store}()
            link = {create_fn}(s, "https://x.com")
            assert {c.name}(s, link.code) == 0
        """)
    return f'pytest.skip("Implement @returns smoke test for {c.entity_id}")'


def render_tests(contracts: list[FunctionContract], regen_cmd: str, src_root: Path, root: Path) -> str:
    imports = _render_imports(contracts, src_root, root)
    store = "LinkStore"
    parts = [HEADER.format(regen_cmd=regen_cmd, imports=imports)]
    for c in contracts:
        parts.append(f"\n# --- {c.entity_id} ---\n")
        parts.append(f"# @intent {c.intent[:120]}{'...' if len(c.intent) > 120 else ''}\n")
        if c.feature:
            parts.append(f"# @feature {c.feature}\n")
        if c.flag:
            parts.append(f"# @flag {c.flag}\n")
        mod_slug = _slug(c.module.replace(".", "_"))
        for exc in c.raises:
            fn = f"test_{mod_slug}_{c.name}_raises_{_slug(exc)}"
            body = _stub_body(c, exc, store)
            parts.append(f"def {fn}():\n")
            parts.append(f'    """Contract @raises {exc} — {c.entity_id}"""\n')
            for line in body.splitlines():
                parts.append(f"    {line}\n" if line else "    \n")
            parts.append("\n")
        smoke = _returns_smoke(c, store, contracts)
        if smoke:
            fn = f"test_{mod_slug}_{c.name}_returns_contract"
            parts.append(f"def {fn}():\n")
            parts.append(f'    """Contract @returns — {c.entity_id}"""\n')
            for line in smoke.splitlines():
                parts.append(f"    {line}\n" if line else "    \n")
            parts.append("\n")
    return "".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.environ.get("GITHUB_WORKSPACE") or ".")
    ap.add_argument("--src", default=None)
    ap.add_argument("--out", default="tests/generated/test_contract_verification.py")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if generated output differs from --out (CI mode)")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    src_root = Path(args.src).resolve() if args.src else root / "src"
    out_path = Path(args.out).resolve() if Path(args.out).is_absolute() else root / args.out

    regen_cmd = (
        "dist-brain-metadata-tooling/engine/generate_verification.py --root ."
    )
    contracts = collect_contracts(src_root, root)
    if not contracts:
        print("No public contracts found — nothing to generate.")
        return 0

    content = render_tests(contracts, regen_cmd, src_root, root)
    if args.check:
        if not out_path.exists():
            print(f"Verification stubs missing: {out_path}")
            print("Run generate_verification.py --root . to create them.")
            return 1
        if out_path.read_text() != content:
            print(f"Contract verification stubs are stale: {out_path}")
            print("Regenerate: python3 .../generate_verification.py --root .")
            return 1
        print(f"Contract verification stubs up to date ✓  ({len(contracts)} function(s))")
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content)
    print(f"Wrote {out_path}  ({len(contracts)} function(s), "
          f"{content.count('def test_')} test(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())