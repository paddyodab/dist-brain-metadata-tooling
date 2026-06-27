# Tokens to orient: with vs without the dist-brain

Single measurement on a bounded-contexts example repo.

## Module chosen

`backend/orders.py` from `examples/bounded-contexts/`.

Why this module:
- It is a real backend module in the dist-brain fixture repo.
- It now has **6 documented public functions**: `list_line_items`, `save_ship_window`,
  `build_order_view`, `validate_ship_window`, `compute_drop_date`, `notify_fulfillment`.
  (The original 3 were expanded to meet the ">= 5 functions" threshold while keeping
  all functions coherent and tagged.)
- It exercises multiple dist-brain concepts at once: `@intent`, `@param`,
  `@returns`, `@raises`, `@flag`, `@feature`, `@adapts` cross-context edge, and uses
  domain terms from `backend/CONTEXT.md`.
- The question "what does this module do and what are its dependencies?" is
  natural: the module lists line items, persists and validates ship windows,
  computes drop dates, notifies fulfillment, and adapts order state into a
  frontend `OrderView`.

## Question being answered

> What does `backend/orders.py` do and what are its dependencies?

## Tokenizer

Method: `cl100k_base` via `tiktoken` if available; otherwise fallback to
`len(text) // 4`.

In this environment `tiktoken` was not installed and the active Python had no
`pip`, so all counts use `len(text) // 4`. This is a rough estimate and tends to
slightly overcount prose relative to cl100k_base. The same estimator is used for
both the "without brain" and "with brain" paths so the ratio is internally
consistent even if the absolute numbers are approximate.

## Preparing the brain

The example repo did not contain a pre-built `brain.sqlite`, so we built one:

```bash
cd /Users/paddyodabb/my-projects/GitHub/dist-brain-metadata-tooling/engine
python3 extract.py --root ../examples/bounded-contexts --src ../examples/bounded-contexts
```

Then upserted the extracted nodes/edges into `brain.sqlite` at
`examples/bounded-contexts/brain.sqlite` using `BrainStore.upsert_main`.

The resulting brain contains 12 nodes (6 backend functions, 3 frontend
functions, 3 flag nodes) and 6 edges (2 raises, 2 gated-by, 2 adapts).

## WITHOUT the brain: read files directly

Simulated agent strategy:
1. Grep for the module filename (`orders.py`) to locate it.
2. Read the module source.
3. Read the per-context glossary (`backend/CONTEXT.md`) and contract vocabulary
   (`backend/contracts.yml`) to understand the domain terms and allowed tags.
4. Read the global `flags.yml` to interpret the `@flag` and `@feature` references.
5. Grep the repo for each function name and for the `OrderView` adapts target to
   find dependencies and callers.

Counts (using `len(text) // 4`):

Files read (4 files):
- `backend/orders.py`: 513 tokens (2054 chars)
- `backend/CONTEXT.md`: 163 tokens (652 chars)
- `backend/contracts.yml`: 168 tokens (673 chars)
- `flags.yml`: 97 tokens (391 chars)

Searches run (8 greps):
- `grep -RIn orders.py`: 0 tokens (0 chars)
- `grep -RIn list_line_items`: 82 tokens (329 chars)
- `grep -RIn save_ship_window`: 38 tokens (152 chars)
- `grep -RIn build_order_view`: 113 tokens (455 chars)
- `grep -RIn validate_ship_window`: 36 tokens (146 chars)
- `grep -RIn compute_drop_date`: 39 tokens (157 chars)
- `grep -RIn notify_fulfillment`: 39 tokens (157 chars)
- `grep -RIn OrderView`: 250 tokens (1001 chars)

Math:
- Files: 513 + 163 + 168 + 97 = 941 tokens
- Searches: 0 + 82 + 38 + 113 + 36 + 39 + 39 + 250 = 597 tokens
- **Total without brain: 941 + 597 = 1538 tokens**

## WITH the brain: MCP tool calls

Simulated agent strategy using the MCP equivalents in `mcp/brain_query.py`:
1. `overview(context="backend")` to get the high-level map (which modules and
   node counts exist in the backend context).
2. `search("orders.py", context="backend")` to find the functions in the module.
3. `get_entity` for each of the 6 functions to retrieve intent, signature,
   raises, flag/feature, and authored edges.
4. `neighbors` for the adapter function (`build_order_view`) to confirm its
   `adapts` target and `gated-by` flag. The other functions' edges are already
   visible inside `get_entity`, so no extra neighbors calls are needed.

This is the realistic minimal path.

Counts (JSON responses, `len(text) // 4`):

| MCP call | Tokens |
|---|---|
| `overview(context="backend")` | 133 |
| `search("orders.py", context="backend")` | 307 |
| `get_entity(backend/orders.py#list_line_items)` | 160 |
| `get_entity(backend/orders.py#save_ship_window)` | 212 |
| `get_entity(backend/orders.py#build_order_view)` | 250 |
| `get_entity(backend/orders.py#validate_ship_window)` | 209 |
| `get_entity(backend/orders.py#compute_drop_date)` | 218 |
| `get_entity(backend/orders.py#notify_fulfillment)` | 176 |
| `neighbors(backend/orders.py#build_order_view)` | 58 |

Math:
- 133 + 307 + 160 + 212 + 250 + 209 + 218 + 176 + 58 = **1723 tokens**
- MCP calls made: **9**

A maximal path that calls `neighbors()` for every function costs 1825 tokens
(14 calls). A minimal path that skips `neighbors` entirely and relies on the
edges already included in `get_entity` costs 1665 tokens (8 calls). The 9-call
realistic path is reported as the primary number.

## Ratio

- Without brain: **1538 tokens**
- With brain: **1723 tokens**
- Ratio (without / with): **1538 / 1723 ≈ 0.89**

So in this measurement the brain path is about **11% more expensive** in tokens.

## Repeatable method

To repeat this on a different module:

1. Build or locate the brain for the repo:
   ```bash
   cd /path/to/dist-brain-metadata-tooling/engine
   python3 extract.py --root /path/to/target/repo --src /path/to/target/src
   # load the JSON output into BrainStore or run materialize.py
   ```

2. Pick a module with >= 5 functions. Record its file path and the names of its
   public functions.

3. WITHOUT brain:
   - Run the file-locating searches you would expect an agent to run.
   - Read the module source plus the relevant `CONTEXT.md`, `contracts.yml`,
     `flags.yml`, and any `README.md` needed to understand vocabulary.
   - Grep for each public function name and for the symbols it imports/calls to
     identify dependencies.
   - Sum `len(text) // 4` (or `tiktoken` cl100k_base) over every file read and
     every grep result string.

4. WITH brain:
   - Use `brain_query.Brain` (or the MCP server tools):
     - `overview(context=...)`
     - `search("<module_file>", context=...)`
     - `get_entity(<id>)` for each function in the module
     - `neighbors(<id>)` for any boundary-crossing function
   - Dump each response to JSON and sum the same tokenizer over the response
     strings.

5. Record both totals, the call/search lists, and the ratio. Note the tokenizer
   and any fallbacks.

## Honest caveats

- **Single measurement** on a tiny repo. An 11% loss is not a guarantee; it could
  flip on a larger or more complex module.
- **Small fixture:** `examples/bounded-contexts/` has only two files of code.
  The "without brain" path is not very expensive because there are few files to
  read and few grep hits. On a large monorepo the without-brain path would
  likely scale worse (more grep noise, more context files to read), while the
  brain path stays roughly constant per function queried. The current negative
  result is partly because the fixture is too small for the brain's per-call
  JSON overhead to amortize.
- **Approximate tokenizer:** `len(text) // 4` is a coarse proxy. Real cl100k_base
  counts would be lower for prose and JSON punctuation, but both paths were
  measured the same way so the ratio is still comparable.
- **No real MCP server:** The calls were executed through `mcp/brain_query.py`
  directly. A real MCP round-trip may add framing overhead per response.
- **Brain was freshly built:** The brain contained exactly this repo. In
  production the brain may be slightly stale; a refresh step would add tokens
  but is outside the orienting question.
- **Agent behavior differs:** A real agent might read extra files or make extra
  search/MCP calls depending on confidence. These numbers describe a deliberate,
  tight orienting strategy, not an upper bound.
- **Result does not include prompt tokens:** Only response/file content tokens
  are counted. The user's or system prompts that ask the question are the same
  in both paths and are ignored.
- **Fixture was modified for this measurement:** Three tagged functions were
  added to `backend/orders.py` to meet the ">= 5 functions" threshold.

---

*Measured on 2026-06-27 by executing the extraction and queries in a local
session. The brain was rebuilt after adding the new functions.*
