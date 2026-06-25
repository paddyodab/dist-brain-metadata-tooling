#!/usr/bin/env python3
"""MCP server exposing the materialized brain as agent query tools.

Sources (DIST_BRAIN_GRAPH):
  - brain.sqlite — canonical store with FTS5 + revisions (preferred at scale)
  - graph.json   — legacy export for small repos

Optional DIST_BRAIN_REVISION (default: main) — query a tag snapshot vs rolling main.

Run:  DIST_BRAIN_GRAPH=brain/brain.sqlite python3 mcp/server.py
Deps: pip install mcp   (Python 3.10+)
"""
import os
import sys

from brain_query import Brain, DEFAULT_REVISION

try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:
    sys.exit("The 'mcp' package is required: pip install mcp")

SOURCE = os.environ.get("DIST_BRAIN_GRAPH", "brain/graph.json")
DEFAULT_REVISION_ENV = os.environ.get("DIST_BRAIN_REVISION", DEFAULT_REVISION)
mcp = FastMCP("dist-brain")


def _brain(revision: str = "") -> Brain:
    rev = revision or DEFAULT_REVISION_ENV
    return Brain(SOURCE, revision=rev).load()


@mcp.tool()
def overview(revision: str = "") -> dict:
    """Get a high-level map of the codebase: entity/flag/decision counts, modules,
    flags, ADRs. Call first. SQLite brains include storage=sqlite and available
    revisions. Use revision= to query a release tag instead of main."""
    return _brain(revision).overview()


@mcp.tool()
def list_revisions() -> list:
    """List materialized revisions (main rolling + release tag snapshots)."""
    return _brain().list_revisions()


@mcp.tool()
def list_sources() -> list:
    """List brain graph sources when DIST_BRAIN_GRAPH joins multiple JSON repos."""
    return _brain().list_sources()


@mcp.tool()
def search(query: str, source: str = "", revision: str = "") -> list:
    """FTS5/search over entity ids, titles, and intent. Cite stable ids in summaries.
    revision= for tag snapshots; source= for joined JSON repos only."""
    return _brain(revision).search(query, source=source or None)


@mcp.tool()
def get_entity(id: str, revision: str = "") -> dict:
    """Fetch one entity by stable id with edges in/out."""
    return _brain(revision).get_entity(id)


@mcp.tool()
def neighbors(id: str, revision: str = "") -> dict:
    """Graph neighbors for impact analysis (raises, gated-by, …)."""
    return _brain(revision).neighbors(id)


@mcp.tool()
def list_decisions(source: str = "", revision: str = "", kind: str = "") -> list:
    """List ADRs with status, kind, and one-line summary. Pass kind='constraint'
    for the house rules (forward-looking premises) or 'record' for retrospective ADRs."""
    return _brain(revision).decisions(source=source or None, kind=kind or None)


@mcp.tool()
def history(id: str, revision: str = "") -> list:
    """Intent-change timeline for an entity: every commit where its @intent changed,
    with the intent text at that point (oldest first) — 'how did this guarantee evolve?'.
    Sourced from the intent_history WAL; sqlite brains only (empty for JSON brains)."""
    return _brain(revision).history(id)


@mcp.tool()
def why(id: str, revision: str = "") -> dict:
    """Why an entity is the way it is: current intent, provenance status
    (verified|inferred), lineage (first_seen/last_touched sha), what governs it
    (flags via gated-by, linked decisions), and how many times its intent changed.
    Pairs with history() for the full when/why provenance story."""
    return _brain(revision).why(id)


if __name__ == "__main__":
    print(
        f"dist-brain MCP listening on stdio ({SOURCE}, revision={DEFAULT_REVISION_ENV})",
        file=sys.stderr,
        flush=True,
    )
    mcp.run()