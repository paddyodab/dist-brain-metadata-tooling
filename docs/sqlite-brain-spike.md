# SQLite brain spike — findings

**Status:** spike (2026-06-22)  
**Homeroom context:** [`my-grok-homeroom/notes/road-trip-2026-06.md`](../../my-grok-homeroom/notes/road-trip-2026-06.md)

## Decision

**`brain.sqlite` is the canonical property graph.** `main` is the rolling revision
(full entity set, incrementally upserted). Release tags are frozen snapshots
(`snapshot_revision`). `graph.json` remains an optional small-repo export.

## Schema (v1)

| Table | Purpose |
|---|---|
| `revisions` | `main` (rolling) + tags (`v1.0`, …) |
| `nodes` | Full entity rows per revision + lineage (`first_seen_sha`, `last_touched_sha`) |
| `edges` | `raises`, `gated-by`, … per revision |
| `nodes_fts` | FTS5 index (porter) for MCP search |
| `intent_history` | Append on `@intent` change (stub for audit) |

## Materializer

```bash
python3 engine/materialize.py --root ../my-app --brain /tmp/wiki
# writes brain.sqlite + Features.md (SQL-rendered) + graph.json (compat)
python3 engine/materialize.py --root . --brain /tmp/wiki --snapshot-ref v1.0
python3 engine/materialize.py --root . --brain /tmp/wiki --no-json   # large-repo mode
```

## MCP

```bash
DIST_BRAIN_GRAPH=brain/brain.sqlite DIST_BRAIN_REVISION=main python3 mcp/server.py
```

New tool: `list_revisions`. Optional `revision=` on query tools for tag history.

## Scale benchmark

```bash
python3 engine/generate_brain_fixture.py --nodes 10000 --out /tmp/large-brain.sqlite
# search('billing custom') typically <50ms on dev hardware
```

## Human projection

- **Proven:** `Features.md` rendered from SQL (`BrainStore.render_features_md`)
- **Wiki:** still hosts markdown; binary `.sqlite` on GitHub wiki TBD (spike #5)
- **Future:** Astro/static site as renderer over same SQL connection

## Not in spike

- Incremental extract (git diff scope) — upsert is incremental, extract still full
- Cross-repo join on SQLite
- Remote SQLite URL hosting (download-to-temp works for spike)

## Go/no-go

| Criterion | Result |
|---|---|
| MCP parity on linkshort | ✓ via export or sqlite |
| FTS5 search at 10k nodes | ✓ |
| SQL-backed wiki slice | ✓ Features.md |
| Incremental upsert | ✓ delta-driven |
| Tag snapshots | ✓ `snapshot_revision` |