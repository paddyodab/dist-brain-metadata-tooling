#!/usr/bin/env python3
"""MCP server exposing the materialized brain as agent query tools.

This is the AGENT projection's *depth* surface (the agent-context.md bundle is
the breadth surface). An MCP client — e.g. Claude Code — connects over stdio and
calls these tools to retrieve exactly the slice it needs instead of loading the
whole brain.

The graph source is set via the DIST_BRAIN_GRAPH env var — a local path or the
raw URL of a repo's wiki graph.json, e.g.
  https://raw.githubusercontent.com/wiki/<owner>/<repo>/graph.json

Run:  DIST_BRAIN_GRAPH=... python3 mcp/server.py
Deps: pip install mcp   (Python 3.10+)
"""
import os
import sys

from brain_query import Brain

try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:
    sys.exit("The 'mcp' package is required: pip install mcp")

SOURCE = os.environ.get("DIST_BRAIN_GRAPH", "brain/graph.json")
mcp = FastMCP("dist-brain")


def _brain() -> Brain:
    # Reload per call so the server always reflects the latest published graph
    # (the brain is regenerated on every merge). The graph is small.
    return Brain(SOURCE).load()


@mcp.tool()
def overview() -> dict:
    """Get a high-level map of the codebase: entity/flag/decision counts, the list
    of modules, feature flags, and architecture decisions (ADRs). Call this first
    to orient before drilling in."""
    return _brain().overview()


@mcp.tool()
def search(query: str) -> list:
    """Search the codebase knowledge graph by keyword across entity ids, titles,
    and intent prose. Returns matching functions, flags, and decisions with their
    stable ids — cite the ids."""
    return _brain().search(query)


@mcp.tool()
def get_entity(id: str) -> dict:
    """Fetch one entity by its stable id (e.g. 'src/linkshort/shorten.py#create_short_link',
    'flag:enable_custom_aliases', 'decision:0001-...'): its intent, facts
    (params/returns/raises/flag), provenance, and the edges in/out of it."""
    return _brain().get_entity(id)


@mcp.tool()
def neighbors(id: str) -> dict:
    """List the graph neighbors of an entity id — what it raises / is gated by
    (outgoing) and what raises or is gated by it (incoming). Use for impact
    analysis without reading prose."""
    return _brain().neighbors(id)


@mcp.tool()
def list_decisions() -> list:
    """List the architecture decision records (ADRs) — the cross-cutting 'why' —
    with status and a one-line summary each."""
    return _brain().decisions()


if __name__ == "__main__":
    mcp.run()
