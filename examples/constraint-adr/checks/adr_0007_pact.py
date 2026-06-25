#!/usr/bin/env python3
"""Deterministic gate for ADR-0007 (Pact contracts).

Invariant: every service directory under ``services/`` ships a ``pacts/`` directory.
Run by ``check_constraints`` from the repo root with ``GITHUB_WORKSPACE`` set; exit 0 if
the invariant holds, 1 (listing the offenders) otherwise. This is the §7.5 ``gate:``
contract — a whole-repo invariant check, not a diff-scoped one.
"""
from __future__ import annotations

import os
from pathlib import Path


def main() -> int:
    root = Path(os.environ.get("GITHUB_WORKSPACE") or ".").resolve()
    services = root / "services"
    if not services.is_dir():
        print("ADR-0007 ✓ no services/ yet — nothing to contract")
        return 0
    missing = [
        svc.relative_to(root).as_posix()
        for svc in sorted(p for p in services.iterdir() if p.is_dir())
        if not (svc / "pacts").is_dir()
    ]
    if missing:
        print("ADR-0007 violated — services without a pacts/ contract dir:")
        for m in missing:
            print(f"  - {m}")
        return 1
    print("ADR-0007 ✓ every service has pacts/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
