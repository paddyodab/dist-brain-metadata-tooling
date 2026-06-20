#!/usr/bin/env python3
"""Generate Gherkin feature files from colocated @intent contracts.

Contracts are the spec; these .feature files are the human/agent-readable BDD
projection. Grouped by @feature; @raises become Then steps; @flag becomes tags.

Usage:
  python3 generate_gherkin.py --root ../my-app-with-a-wiki-01
  python3 generate_gherkin.py --root . --check   # CI: fail if features are stale

Wire to pytest-bdd later with step definitions; today they are spec artifacts
for review, orchestrator handoffs, and documentation.
"""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

from contract_lib import FunctionContract, collect_contracts

HEADER = """# Generated from colocated metadata — do not edit STRUCTURE by hand.
# Regenerate: python3 {regen_cmd}
# @intent prose becomes scenario descriptions; @raises become Then steps.
"""

_SCENARIO_RE = re.compile(r"[^a-z0-9]+")


def _slug(s: str) -> str:
    return _SCENARIO_RE.sub("_", s.lower()).strip("_") or "scenario"


def _feature_slug(name: str) -> str:
    return _slug(name.replace("-", " "))


def _scenario_name(c: FunctionContract, suffix: str = "") -> str:
    base = f"{c.name}{suffix}"
    return _slug(base)


def _indent(lines: list[str], spaces: int = 4) -> list[str]:
    pad = " " * spaces
    return [f"{pad}{line}" if line else "" for line in lines]


def _raises_step(exc: str, fn: str) -> str:
    return f"Then {exc} is raised by {fn}"


def _scenario_block(c: FunctionContract) -> list[str]:
    lines = [
        f"  Scenario: {_scenario_name(c)}",
        f"    # {c.entity_id}",
    ]
    if c.flag:
        lines.insert(0, f"  @flag:{c.flag}")
    lines.append(f"    # @intent {c.intent}")
    lines.append("    Given a link store")
    if c.params:
        args = ", ".join(f'"{p}"' for p in c.params if p != "store")
        if args:
            lines.append(f"    When {c.name} is called with {args}")
        else:
            lines.append(f"    When {c.name} is called")
    else:
        lines.append(f"    When {c.name} is called")
    if c.raises:
        for exc in c.raises:
            lines.append(f"    {_raises_step(exc, c.name)}")
    elif c.returns:
        lines.append(f"    Then {c.name} returns a value matching the contract")
    else:
        lines.append(f"    Then {c.name} behaves per contract")
    lines.append("")
    return lines


def _flag_scenario(c: FunctionContract, enabled: bool) -> list[str]:
    state = "on" if enabled else "off"
    lines = [
        f"  @flag:{c.flag}",
        f"  Scenario: {_scenario_name(c, f'_flag_{state}')}",
        f"    # {c.entity_id} — flag {c.flag} is {state}",
        f"    Given flag {c.flag} is {state}",
        "    And a link store",
        f"    When {c.name} is invoked per contract",
        f"    Then behavior matches @intent with flag {state}",
        "",
    ]
    return lines


def render_feature(feature: str, contracts: list[FunctionContract], regen_cmd: str) -> str:
    intents = [c.intent for c in contracts if c.intent]
    summary = intents[0][:200] if intents else f"Contracts for feature {feature}"
    parts = [
        HEADER.format(regen_cmd=regen_cmd),
        f"Feature: {feature}",
        f"  {summary}",
        "",
    ]
    for c in contracts:
        parts.extend(_scenario_block(c))
    flagged = [c for c in contracts if c.flag]
    if flagged:
        parts.append("  # Flag-gated scenarios (matrix: on and off)")
        parts.append("")
        for c in flagged:
            parts.extend(_flag_scenario(c, enabled=False))
            parts.extend(_flag_scenario(c, enabled=True))
    return "\n".join(parts).rstrip() + "\n"


def render_all(contracts: list[FunctionContract], regen_cmd: str) -> dict[str, str]:
    by_feature: dict[str, list[FunctionContract]] = {}
    for c in contracts:
        key = c.feature or "core"
        by_feature.setdefault(key, []).append(c)
    return {
        f"{_feature_slug(name)}.feature": render_feature(name, group, regen_cmd)
        for name, group in sorted(by_feature.items())
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.environ.get("GITHUB_WORKSPACE") or ".")
    ap.add_argument("--src", default=None)
    ap.add_argument("--out-dir", default="tests/generated/features")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if generated output differs (CI mode)")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    src_root = Path(args.src).resolve() if args.src else root / "src"
    out_dir = Path(args.out_dir).resolve() if Path(args.out_dir).is_absolute() else root / args.out_dir

    regen_cmd = "dist-brain-metadata-tooling/engine/generate_gherkin.py --root ."
    contracts = collect_contracts(src_root, root)
    if not contracts:
        print("No public contracts found — nothing to generate.")
        return 0

    files = render_all(contracts, regen_cmd)
    if args.check:
        stale = []
        for name, content in files.items():
            path = out_dir / name
            if not path.exists() or path.read_text() != content:
                stale.append(path)
        if stale:
            print("Gherkin features are stale or missing:")
            for p in stale:
                print(f"  {p}")
            print("Regenerate: python3 .../generate_gherkin.py --root .")
            return 1
        print(f"Gherkin features up to date ✓  ({len(files)} file(s), "
              f"{len(contracts)} function(s))")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (out_dir / name).write_text(content)
    print(f"Wrote {len(files)} feature file(s) to {out_dir}  ({len(contracts)} function(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())