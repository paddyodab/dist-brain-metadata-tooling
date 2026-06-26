# CONTEXT-MAP.md format

A `CONTEXT-MAP.md` lives at the root of a repo and declares the bounded contexts
that make up that repo. It is **optional and authoritative**: when it is present,
the context resolver uses it as the single source of truth; when it is absent,
the resolver falls back to walking up the directory tree looking for
`CONTEXT.md` files.

This file is for two audiences:

1. **Humans** — new contributors read one table and know which glossary,
   contracts, decisions, and house rules apply to the code they are touching.
2. **The context resolver** — an explicit map removes ambiguity when a context's
   files are spread across non-contiguous directories or when the walk-up logic
   would otherwise pick the wrong boundary.

---

## File location and precedence

- Location: repository root (`/CONTEXT-MAP.md`).
- Precedence: when present, `CONTEXT-MAP.md` is **authoritative**.
- Fallback: when absent, `resolve_context()` walks up from the file to the nearest
  `CONTEXT.md`.
- A repo can mix both modes: map authoritative contexts, and any directory with a
  `CONTEXT.md` that is not in the map is resolved by walk-up.

---

## Table format

The context map is a Markdown table with exactly these columns:

| Column      | Required | Description |
|-------------|----------|-------------|
| `Context`   | yes      | Short, URL-friendly identifier used as the `context` value on nodes. Must match `[a-z0-9_-]+`. Examples: `backend`, `frontend`, `order-adapter`. |
| `Location`  | yes      | Directory path relative to repo root, ending with `/`. Use `*` for a context whose files are spread across multiple directories (see multi-location example below). |
| `Kind`      | yes      | One of `service`, `component`, `data`, `infra`, or `adapter`. An `adapter` context sits on a boundary and translates between two or more other contexts. |
| `Description` | yes    | One-line human summary of what the context owns. |

Only the first table in the file is parsed. Rows whose `Context` cell is empty,
is exactly `Context`, or starts with `-` are treated as the header or a separator
and are ignored.

---

## Example: two-context monorepo

```markdown
# Context Map

This repo has two bounded contexts: a FastAPI backend and a React frontend.

| Context  | Location   | Kind      | Description                          |
|----------|------------|-----------|--------------------------------------|
| backend  | backend/   | service   | FastAPI API server and domain model   |
| frontend | frontend/  | component | React SPA and UI components           |
```

With this map:

- `backend/src/services/order.py` resolves to `backend`.
- `frontend/src/components/Cart.tsx` resolves to `frontend`.
- Any file not under `backend/` or `frontend/` resolves to the root context
  (`None` / `"root"`), or uses walk-up fallback if root has a `CONTEXT.md`.

Each context owns its own supporting files alongside its source directory:

- `backend/CONTEXT.md` — glossary
- `backend/contracts.yml` — valid `@tags`
- `backend/decisions/` — ADRs
- `backend/house-rules/` — forward-looking constraints

---

## Example: three-context monorepo with an adapter

```markdown
# Context Map

The backend exposes an Order API. The frontend renders a cart. The adapter
context owns the API client and the type translation between backend DTOs and
frontend view models.

| Context  | Location   | Kind      | Description                                     |
|----------|------------|-----------|-------------------------------------------------|
| backend  | backend/   | service   | FastAPI API server, domain model, and database  |
| frontend | frontend/  | component | React SPA, UI components, and browser state     |
| adapter  | adapter/   | adapter   | API client + backend/frontend type translation  |
```

An `adapter` context is special: it does not own business logic, it owns the
**boundary contract** between two contexts. Its `contracts.yml` will typically
require tags like `@adapts` and `@maps_to` instead of backend-only tags like
`@raises` or frontend-only tags like `@renders`.

Expected resolution:

- `backend/src/orders/repository.py` → `backend`
- `frontend/src/cart/Cart.tsx` → `frontend`
- `adapter/src/order_client.ts` → `adapter`

---

## Example: non-contiguous locations

If a context's files are split across directories that do not share a single
parent, set `Location` to `*` and rely on walk-up fallback via `CONTEXT.md` files in
those directories, or list the primary directory and let nested `CONTEXT.md`
files override for the exceptions.

```markdown
| Context      | Location     | Kind      | Description                                     |
|--------------|--------------|-----------|-------------------------------------------------|
| shared-kernel| libs/shared/ | data      | Domain primitives used by backend and frontend  |
| backend      | backend/     | service   | FastAPI API server                              |
| frontend     | frontend/    | component | React SPA                                       |
```

In this case `shared-kernel` is authoritative, while `backend` and `frontend` use
normal directory mapping. The `*` convention prevents the resolver from inventing
a wrong path-based context name.

---

## Resolver behavior

When `CONTEXT-MAP.md` exists at the root, `resolve_context(file_path, root)`:

1. Parses the first Markdown table.
2. For each row, records `Location` → `Context`.
3. Resolves a file by matching its relative path against the longest matching
   mapped location. If `backend/src/services/order.py` is checked against the
   three-context example, `backend/` matches and is longer than any other match,
  so the resolved context is `backend`.
4. If no mapped location matches, falls back to walk-up resolution.
5. If walk-up also finds nothing, returns `None` (single-context / root behavior).

This is the same precedence rule as contracts in the engine: explicit map wins,
then automatic discovery, then default.

---

## Validation hints

- Keep the table sorted by `Context` so diffs stay readable.
- Use lowercase, hyphen-separated identifiers. `backend-adapter` is fine;
  `BackendAdapter` is not.
- One `Location` per row in the common case. Use `*` only when a context is
  genuinely scattered.
- If a context is missing its `CONTEXT.md`, the map still resolves the name, but
  downstream tooling (gate, glossary check, MCP search) will treat the glossary
  and contracts for that context as absent.

---

## Companion files

For each row in the map, the resolver expects these optional companion files at
`{Location}`:

- `CONTEXT.md` — the glossary for that context.
- `contracts.yml` — the valid `@tags` and required/optional rules for that context.
- `decisions/` — ADRs specific to that context.
- `house-rules/` — forward-looking, enforceable constraints scoped to that context.

A context without these files still resolves, but behaves like a single-context
repo for gate and search purposes.
