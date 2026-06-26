"""Resolve which bounded context a source file belongs to.

A file's context is determined in order of precedence:

1. An explicit CONTEXT-MAP.md at the root (authoritative).
2. The nearest directory (walking up from the file) that contains a CONTEXT.md.
3. None (= root = single-context repo = today's behavior).
"""
from __future__ import annotations

from pathlib import Path


def _is_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _load_context_map(root: Path) -> dict[str, str]:
    """Parse the first Markdown table in root/CONTEXT-MAP.md.

    Returns {location: context} for every non-header row. Locations end with '/'
    (or '*' for non-contiguous / wildcard contexts). Empty or invalid tables
    return an empty dict.
    """
    path = root / "CONTEXT-MAP.md"
    if not path.exists():
        return {}

    mapping: dict[str, str] = {}
    in_table = False
    for raw in path.read_text().splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not stripped.startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in stripped.split("|")]
        # Drop the leading and trailing empty cells produced by the outer pipes.
        cells = cells[1:-1]
        if not cells:
            continue
        if not in_table:
            in_table = True
            header = [c.lower() for c in cells]
            if "context" not in header or "location" not in header:
                # Not a context-map table.
                in_table = False
                continue
            continue
        if all(c.replace("-", "") == "" for c in cells):
            continue
        if "context" in [c.lower() for c in cells]:
            continue
        if len(cells) < 4:
            continue
        context = cells[0]
        location = cells[1]
        if not context or context.lower() == "context":
            continue
        mapping[location] = context
    return mapping


def _context_from_map(file_path: Path, root: Path) -> str | None:
    """Return the context from CONTEXT-MAP.md if the file matches a location."""
    mapping = _load_context_map(root)
    if not mapping:
        return None
    rel_parts = file_path.resolve().relative_to(root.resolve()).parts
    # Find the longest matching mapped location prefix. A location of '.' or ''
    # represents the root context and matches any file inside root.
    best_ctx: str | None = None
    best_depth = -1
    for location, context in mapping.items():
        if location == "*":
            continue
        normalized = location.strip().rstrip("/")
        if normalized in ("", "."):
            if best_depth < 0:
                best_depth = 0
                best_ctx = context
            continue
        loc_parts = tuple(normalized.split("/"))
        if len(loc_parts) <= len(rel_parts) and rel_parts[: len(loc_parts)] == loc_parts:
            if len(loc_parts) > best_depth:
                best_depth = len(loc_parts)
                best_ctx = context
    return best_ctx


def resolve_context(file_path: Path, root: Path) -> str | None:
    """Resolve a file's bounded context.

    Precedence:
      1. CONTEXT-MAP.md (authoritative).
      2. Nearest CONTEXT.md by walking up from the file.
      3. None if neither exists (single-context repo = today's behavior).

    Returns the context name (directory path relative to root, or "root" when the
    root itself contains CONTEXT.md), or None.
    """
    root = root.resolve()
    file_path = file_path.resolve()
    try:
        file_path.relative_to(root)
    except ValueError:
        return None

    # 1. Authoritative map.
    mapped = _context_from_map(file_path, root)
    if mapped is not None:
        return mapped if mapped != "root" else "root"

    # 2. Walk up from the file's directory toward (but not past) root.
    start = file_path.parent
    chain = [start]
    for d in start.parents:
        if d == root or not _is_under(d, root):
            break
        chain.append(d)
    # Check nearest first.
    for d in chain:
        if (d / "CONTEXT.md").exists():
            rel = d.relative_to(root)
            return str(rel) if str(rel) != "." else "root"

    # Root itself is the final fallback.
    if (root / "CONTEXT.md").exists():
        return "root"
    return None


def context_dir(root: Path, context: str | None) -> Path:
    """Return the directory for a context name (or root for None/'root')."""
    root = root.resolve()
    if context is None or context == "root":
        return root
    return root / context


def contracts_path(root: Path, context: str | None) -> Path:
    """Return the path to contracts.yml for a context."""
    return context_dir(root, context) / "contracts.yml"


def glossary_path(root: Path, context: str | None) -> Path:
    """Return the path to CONTEXT.md for a context."""
    return context_dir(root, context) / "CONTEXT.md"
