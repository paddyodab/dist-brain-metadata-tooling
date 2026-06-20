#!/usr/bin/env python3
"""Generate flag on/off matrix tests from @flag contracts and flags.yml.

For every gated function, emit paired tests: flag off (blocked or default path)
and flag on (feature available). Uses FLAG_<NAME>=true|false env convention
until the app provides a dedicated flags module.

Usage:
  python3 generate_flag_matrix.py --root ../my-app-with-a-wiki-01
  python3 generate_flag_matrix.py --root . --check
"""
from __future__ import annotations

import argparse
import os
import textwrap
from pathlib import Path

from contract_lib import FunctionContract, collect_contracts, module_import_path
from flags_registry import load_flags

HEADER = '''\
"""Flag-matrix verification — generated from @flag contracts + flags.yml.

Do not edit STRUCTURE by hand. Regenerate:
  python3 {regen_cmd}

Convention: tests set FLAG_<UPPER_SNAKE>=true|false via monkeypatch.setenv.
Implement bodies until both on and off paths match @intent.
"""
# fmt: off — generated file
import os

import pytest

{imports}


def _flag_env(name: str, enabled: bool, monkeypatch) -> None:
    key = "FLAG_" + name.upper()
    monkeypatch.setenv(key, "true" if enabled else "false")


'''

def _matrix_body(flag: str, enabled: bool, entity_id: str, state: str, default) -> str:
    return textwrap.dedent(f"""\
        _flag_env({flag!r}, {enabled}, monkeypatch)
        pytest.skip(
            "Implement flag-matrix: {entity_id} with {flag}={state} "
            "(see @intent and flags.yml default={default})"
        )
    """)


def _slug(s: str) -> str:
    out = []
    for ch in s:
        out.append(ch if ch.isalnum() else "_")
    slug = "".join(out).strip("_").lower()
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "fn"


def _render_imports(contracts: list[FunctionContract]) -> str:
    by_mod: dict[str, list[str]] = {}
    for c in contracts:
        if c.flag:
            by_mod.setdefault(c.module, []).append(c.name)
    lines = []
    for mod in sorted(by_mod):
        names = sorted(set(by_mod[mod]))
        lines.append(f"from {mod} import {', '.join(names)}")
    return "\n".join(lines) if lines else "pass  # no flagged contracts"


def render_flag_matrix(
    contracts: list[FunctionContract],
    flags_path: Path,
    regen_cmd: str,
) -> str | None:
    flagged = [c for c in contracts if c.flag]
    if not flagged:
        return None
    registry = load_flags(flags_path)
    parts = [HEADER.format(regen_cmd=regen_cmd, imports=_render_imports(flagged))]
    for c in flagged:
        meta = registry.get(c.flag or "", {})
        default = meta.get("default", False)
        mod_slug = _slug(c.module.replace(".", "_"))
        flag_slug = _slug(c.flag or "flag")
        parts.append(f"\n# --- {c.entity_id} @flag {c.flag} (default={default}) ---\n")
        for enabled in (False, True):
            state = "on" if enabled else "off"
            fn = f"test_{mod_slug}_{c.name}_flag_{flag_slug}_{state}"
            body = _matrix_body(c.flag or "", enabled, c.entity_id, state, default)
            parts.append(f"def {fn}(monkeypatch):\n")
            parts.append(f'    """@flag {c.flag} {state} — {c.entity_id}"""\n')
            for line in body.splitlines():
                parts.append(f"    {line}\n" if line else "\n")
            parts.append("\n")
    return "".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.environ.get("GITHUB_WORKSPACE") or ".")
    ap.add_argument("--src", default=None)
    ap.add_argument("--flags", default="flags.yml")
    ap.add_argument("--out", default="tests/generated/test_flag_matrix.py")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    src_root = Path(args.src).resolve() if args.src else root / "src"
    flags_path = root / args.flags
    out_path = Path(args.out).resolve() if Path(args.out).is_absolute() else root / args.out

    regen_cmd = "dist-brain-metadata-tooling/engine/generate_flag_matrix.py --root ."
    contracts = collect_contracts(src_root, root)
    content = render_flag_matrix(contracts, flags_path, regen_cmd)
    if content is None:
        if args.check and out_path.exists():
            print(f"Remove stale flag-matrix file (no @flag contracts): {out_path}")
            return 1
        print("No @flag contracts — skipping flag-matrix generation.")
        return 0

    if args.check:
        if not out_path.exists():
            print(f"Flag-matrix stubs missing: {out_path}")
            return 1
        if out_path.read_text() != content:
            print(f"Flag-matrix stubs are stale: {out_path}")
            return 1
        flagged = sum(1 for c in contracts if c.flag)
        print(f"Flag-matrix stubs up to date ✓  ({flagged} gated function(s))")
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content)
    flagged = sum(1 for c in contracts if c.flag)
    print(f"Wrote {out_path}  ({flagged} gated function(s), "
          f"{content.count('def test_')} test(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())