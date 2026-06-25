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
   When graphs are joined, includes `joined: true` and per-source metadata.
2. **`dist_brain__list_sources`** — slugs when `DIST_BRAIN_GRAPH` joins multiple repos.
3. **`dist_brain__search`** — keyword search across ids, titles, intent prose.
   Optional `source` param scopes to one joined repo.
4. **`dist_brain__get_entity`** — full record for one stable id (cite ids in summaries).
   Joined ids are prefixed: `my-app:src/linkshort/shorten.py#create_short_link`.
5. **`dist_brain__neighbors`** — graph edges in/out for impact analysis.
6. **`dist_brain__list_decisions`** — all ADRs; optional `source` when joined.
7. **`dist_brain__why`** — provenance for one id: current intent, status
   (verified|inferred), lineage shas, what governs it, intent-change count. "Why is it this way?"
8. **`dist_brain__history`** — the intent-change timeline for one id (each commit where its
   `@intent` changed). "How did this guarantee evolve?" Sqlite brains only.

### Cross-repo join

Set `DIST_BRAIN_GRAPH` to comma-separated `slug|url` pairs:

```
my-app|https://raw.githubusercontent.com/wiki/owner/my-app/graph.json,
lib-foo|https://raw.githubusercontent.com/wiki/owner/lib-foo/graph.json
```

Or a JSON array: `[{"slug":"my-app","url":"https://..."}]`

Use `search_tool` to discover these if needed, then `use_tool` to call them.

## Workflow

1. `overview` to orient.
2. `search` or `get_entity` for the slice you need.
3. `why` / `history` before changing a contract — what it guarantees, why, and how its
   intent has shifted over time (don't relitigate a resolved decision).
4. `neighbors` if the change might propagate (exceptions, flags, calls).
5. When authoring changes, use `/feature` or `/infra` to capture intent at plan time.

## If MCP is unavailable

Fall back to: `CONTRIBUTING.md`, `decisions/`, `flags.yml`, and local
`engine/check_metadata.py --root .`. The brain is a convenience layer over those
sources — not a replacement.