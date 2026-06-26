#!/usr/bin/env python3
"""House-rules gate (rung 3) — deterministic, stdlib-only.

Loads accepted house rules from ``house-rules/*.yml`` and enforces each per its
``enforcement`` (§3 ADR fidelity ladder):

  * ``advisory``      → rung 2 only. A premise injected into grilling / ``/feature``;
                        not gated here. Reported so the engineer sees the house rules.
  * ``deterministic`` → run the rule's ``gate:`` script; a nonzero exit FAILS the build.
  * ``semantic``      → needs an LLM reviewer (freshness-review's sibling). Reported as
                        an advisory notice here; the actual check runs in /code-review.

Only ``status: accepted`` rules are enforced. Proposed/superseded rules are inert.

Gate-script contract (deterministic): the script is run from the repo root with
``GITHUB_WORKSPACE`` set to the root; ``*.py`` gates run under the current interpreter,
anything else is executed directly. Exit 0 = rule holds, nonzero = violated. A
``gate:`` that is missing on disk — or a ``deterministic`` rule with no ``gate:`` at
all — fails closed (a rule that claims to be enforced but can't run is broken, not green).

Usage: python3 check_constraints.py [--root DIR]
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from extract import house_rules_nodes

ENFORCEMENTS = ("advisory", "semantic", "deterministic")


def run_gate(root: Path, gate_rel: str) -> tuple[bool, str]:
    """Run a rule's gate script from ``root``. Returns ``(ok, detail)``."""
    gate_abs = (root / gate_rel)
    if not gate_abs.exists():
        return False, f"gate script not found: {gate_rel}"
    cmd = [sys.executable, str(gate_abs)] if gate_abs.suffix == ".py" else [str(gate_abs)]
    env = {**os.environ, "GITHUB_WORKSPACE": str(root)}
    try:
        proc = subprocess.run(cmd, cwd=str(root), env=env,
                              capture_output=True, text=True)
    except OSError as exc:
        return False, f"gate failed to launch: {exc}"
    detail = (proc.stdout + proc.stderr).strip()
    return proc.returncode == 0, detail


def check_constraints(root: Path) -> dict:
    """Evaluate accepted house rules. Returns a result dict with failures,
    advisory notices (advisory + semantic), and counts."""
    rules = [
        n for n in house_rules_nodes(root)
        if (n["facts"].get("status") or "").lower() == "accepted"
    ]
    failures: list[tuple[str, str, str]] = []   # (id, title, reason)
    advisories: list[tuple[str, str, str]] = []  # (id, title, enforcement)
    checked = 0
    for rule in rules:
        facts = rule["facts"]
        ref, title = rule["id"], rule["title"]
        enf = (facts.get("enforcement") or "advisory").lower()
        if enf == "advisory":
            advisories.append((ref, title, "advisory"))
        elif enf == "semantic":
            advisories.append((ref, title, "semantic"))
        elif enf == "deterministic":
            checked += 1
            gate = facts.get("gate")
            if not gate:
                failures.append((ref, title, "enforcement=deterministic but no gate: declared"))
                continue
            ok, detail = run_gate(root, gate)
            if not ok:
                failures.append((ref, title, detail or f"gate {gate} exited nonzero"))
        else:
            failures.append((ref, title, f"unknown enforcement {enf!r} (expected one of {ENFORCEMENTS})"))
    return {
        "failures": failures,
        "advisories": advisories,
        "checked": checked,
        "total": len(rules),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.environ.get("GITHUB_WORKSPACE") or ".")
    args = ap.parse_args()
    root = Path(args.root).resolve()

    result = check_constraints(root)
    advisories, failures = result["advisories"], result["failures"]

    if advisories:
        print("House rules (forward-looking premises, not gated here):")
        for ref, title, enf in advisories:
            tail = " — needs LLM review (intended for /code-review; not yet wired)" if enf == "semantic" else ""
            print(f"  • [{enf}] {title}  `{ref}`{tail}")
        print()

    if failures:
        print("House-rule check FAILED:\n")
        for ref, title, reason in failures:
            print(f"  ✗ {title}  `{ref}`")
            for line in (reason or "").splitlines() or ["(no detail)"]:
                print(f"      {line}")
        print(f"\n{len(failures)} house rule(s) violated. A house rule can't regress.")
        return 1

    print(f"House-rule check passed ✓  "
          f"({result['checked']} deterministic gate(s) run, {result['total']} accepted rule(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
