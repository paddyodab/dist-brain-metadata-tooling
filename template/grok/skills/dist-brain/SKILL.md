---
name: dist-brain
description: >
  Query the materialized distributed brain for this repo via MCP. Use when exploring
  a codebase with colocated metadata, orienting in an unfamiliar module, checking
  ADRs/flags, or before changing contracts. Run /dist-brain or ask "what does the
  brain say about X?"
metadata:
  short-description: "Query the materialized brain via MCP"
---

# Query the Distributed Brain

This repo (or a sibling consumer repo) may have a **materialized brain** — a
`graph.json` projected from colocated metadata on every merge. The `dist-brain` MCP
server exposes it as query tools. Use these instead of re-scanning the whole repo.

## When to use

- Orienting in an unfamiliar codebase or module
- Finding what a function guarantees before changing it
- Checking feature flags, ADRs, or infra intent
- Impact analysis (what raises what, what a flag gates)

## MCP tools (namespace: `dist_brain__`)

1. **`dist_brain__overview`** — call first. Module list, flag list, ADR index, counts.
2. **`dist_brain__search`** — keyword search across ids, titles, intent prose.
3. **`dist_brain__get_entity`** — full record for one stable id (cite ids in summaries).
4. **`dist_brain__neighbors`** — graph edges in/out for impact analysis.
5. **`dist_brain__list_decisions`** — all ADRs with status and one-line summary.

Use `search_tool` to discover these if needed, then `use_tool` to call them.

## Workflow

1. `overview` to orient.
2. `search` or `get_entity` for the slice you need.
3. `neighbors` if the change might propagate (exceptions, flags, calls).
4. When authoring changes, use `/feature` or `/infra` to capture intent at plan time.

## If MCP is unavailable

Fall back to: `CONTRIBUTING.md`, `decisions/`, `flags.yml`, and local
`engine/check_metadata.py --root .`. The brain is a convenience layer over those
sources — not a replacement.