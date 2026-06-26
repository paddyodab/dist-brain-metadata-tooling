"""Resolve which bounded context a source file belongs to.

A file's context is the nearest directory (walking up from the file) that contains
a CONTEXT.md file. If no CONTEXT.md is found, the context is None (= root = today's
behavior).
"""
from __future__ import annotations

from pathlib import Path


def _is_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def resolve_context(file_path: Path, root: Path) -> str | None:
    """Walk up from file_path to find the nearest CONTEXT.md.

    Returns the context name (directory path relative to root, or "root" when the
    root itself contains CONTEXT.md), or None if no CONTEXT.md is found
    (single-context repo = today's behavior).
    """
    root = root.resolve()
    file_path = file_path.resolve()
    try:
        file_path.relative_to(root)
    except ValueError:
        return None

    # Walk up from the file's directory toward (but not past) root.
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
