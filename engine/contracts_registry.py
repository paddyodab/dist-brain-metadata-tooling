"""Minimal reader for contracts.yml (stdlib only — no PyYAML).

    context: backend
    kind: service
    valid_tags:
      intent:
        required: true
        description: "..."
      param:
        required: auto
        description: "..."
      ...

Returns {tag_name: {required: "true"|"false"|"auto", description: str}}.
"""
from __future__ import annotations

from pathlib import Path


def _scalar(v: str):
    v = v.strip().strip('"').strip("'")
    if v == "true":
        return "true"
    if v == "false":
        return "false"
    if v == "auto":
        return "auto"
    return v


def load_contracts(path) -> dict[str, dict]:
    """Load a contracts.yml and return its valid_tags section as a flat dict.

    If ``path`` does not exist, return {} so callers can fall back to a default
    contract set (today's hardcoded tags).
    """
    p = Path(path)
    if not p.exists():
        return {}
    tags: dict[str, dict] = {}
    current = None
    in_valid = False
    for raw in p.read_text().splitlines():
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        stripped = raw.strip()
        if indent == 0:
            in_valid = stripped.startswith("valid_tags:")
            current = None
        elif in_valid and indent == 2 and stripped.endswith(":"):
            current = stripped[:-1]
            tags[current] = {}
        elif in_valid and indent >= 4 and current and ":" in stripped:
            key, _, value = stripped.partition(":")
            tags[current][key.strip()] = _scalar(value)
    return tags
