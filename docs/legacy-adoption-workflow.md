# Legacy adoption workflow

**Status:** canonical walkthrough · **Last updated:** 2026-06-23

How to take an **existing** codebase (no `@intent`, uneven docs) through inference →
ratification → local brain → verification **incrementally** — without pretending it is
greenfield on day one.

Validated on the RealWorld FastAPI sandbox (`app/` layout, Python 3.10, Poetry).
Adapt paths (`--src app` vs `src/`) and runtime for your consumer repo.

**Related:**

- [`verification-loop.md`](verification-loop.md) — done predicate, work packets (greenfield + end-state)
- [`sqlite-brain-spike.md`](sqlite-brain-spike.md) — local `brain.sqlite`, MCP, wiki artifacts
- [`SETUP.md`](../SETUP.md) — install kit, MCP, wiki token

---

## Greenfield vs legacy

| | Greenfield (`/feature`) | Legacy (this doc) |
|---|-------------------------|-------------------|
| Starting rung | Contracts at write time | Rung 0 — sparse brain |
| Gate scope | All public functions | **Boy-scout** (touched only) — *planned*; today full-repo gate |
| Inference | You write `@intent` | `infer_intent.py` drafts → you ratify |
| Provenance | `verified` at authoring | `inferred` → engineer flips to `verified` |
| pytest | Stubs should pass | Stubs **skip** until implemented |
| `scripts/brain verify` | Use before merge | Use only when gate scope matches your coverage |

---

## One-time setup (consumer repo)

### 1. Install the authoring kit

```bash
git clone https://github.com/paddyodab/dist-brain-metadata-tooling
./dist-brain-metadata-tooling/init.sh /path/to/your-repo <your-gh-user>/<your-repo>
```

Installs Grok skills (`/feature`, `/brain-ops`, `/verification`, `/dist-brain`, …),
`scripts/brain`, and `brain.conf.example`.

### 2. Local config

```bash
cd /path/to/your-repo
cp brain.conf.example brain.conf
```

Edit `brain.conf` (do not commit — machine-local paths):

```bash
BRAIN_SRC=app                              # or src
BRAIN_DIR=/tmp/your-repo-brain             # local wiki + sqlite output
DIST_BRAIN_ENGINE=/path/to/.../engine      # tooling checkout
```

### 3. Python / deps (old lockfiles)

Legacy Poetry lockfiles may pin wheels only for older Python (e.g. PyYAML 6.0 → cp310).
Use a compatible runtime (often **3.10** or **3.11**), not necessarily latest:

```bash
mise use python@3.10
mise use pipx:poetry@latest    # if poetry is a mise shim
poetry env use $(mise which python)
poetry install --no-root
```

If `aiosql` complains about `pkg_resources`, pin `setuptools>=68,<81` in `pyproject.toml`.

### 4. Environment for app tests

```bash
cp .env.example .env
# RealWorld-style: APP_ENV=dev so Alembic reads .env, not prod.env
docker compose up -d db
poetry run alembic upgrade head
```

### 5. Fork, not upstream

Point `origin` at **your** GitHub repo before wiki publish or pushes. Keep upstream
read-only if you want to pull original changes:

```bash
git remote set-url origin https://github.com/<you>/<your-fork>.git
git remote add upstream https://github.com/<original>/<repo>.git   # optional
```

### 6. Grok working directory

**Start Grok in the consumer repo** (not the homeroom). That loads `.grok/skills/`,
`.grok/config.toml`, `scripts/brain`, and `brain.conf`.

Point MCP at local brain after first materialize:

```toml
# .grok/config.toml
DIST_BRAIN_GRAPH = "/tmp/your-repo-brain/brain.sqlite"
DIST_BRAIN_REVISION = "main"
```

---

## The incremental loop (one slice)

Each slice is a module, package, or vertical feature — not the whole repo.

```
┌─────────────┐    ┌──────────────┐    ┌─────────────┐    ┌──────────────┐
│   INFER     │ →  │   RATIFY     │ →  │  MATERIALIZE │ →  │   GENERATE   │
│ draft queue │    │ docstrings   │    │ local wiki  │    │ stubs/gherkin│
└─────────────┘    └──────────────┘    └─────────────┘    └──────────────┘
       ↑                  │                     │                    │
       │            engineer approves          │                    ↓
       │            @intent + @feature         │            ┌──────────────┐
       │            provenance: verified       │            │  (optional)  │
       └──────── scripts/brain status ─────────┴────────────│ implement    │
                                                             │ stub bodies  │
                                                             └──────────────┘
```

### Step 1 — Infer

Pick a scope (file or directory):

```bash
./scripts/brain infer app/services/articles.py
# or
./scripts/brain infer app/services
```

Output: **`inference-queue.md`** at repo root — draft `@intent`, suggested `@feature`,
`@provenance status: inferred`, `@param`, `@returns`, `@raises`, plus git/caller context.

**Grok prompt (equivalent):** `infer app/services/authentication.py`

### Step 2 — Review the queue

Open `inference-queue.md`. For each symbol:

| Your call | Action |
|-----------|--------|
| **Approve** | Paste draft into docstring; set `@provenance status: verified`; add `ratified_at` |
| **Edit** | Revise `@intent` / `@feature`; then paste |
| **Reject** | Skip or rewrite from scratch |

`@feature` is **optional** grouping (wiki Features page, Gherkin). Infer suggests from
module path (`articles.py` → `@feature articles`); confirm, rename, or delete at ratify.

**Grok prompts:**

- `Approve all three as written`
- `Approve #1 and #3; edit #2 @intent to …`
- `Ratify only app/services/jwt.py drafts`

There is no magic slash command for ratify — it is the same checkpoint as `/feature`:
**you sign off on contracts.**

### Step 3 — Local progress check

```bash
./scripts/brain status
```

Terminal report (pytest-cov analogue):

- `@intent` % overall and per module
- `@feature` % (if you added features)
- inference queue backlog
- paths to local wiki (`BRAIN_DIR/Home.md`, `agent-context.md`, `Changelog.md`)

No GitHub merge required — materialize writes the **same** markdown the wiki gets.

### Step 4 — Materialize

```bash
./scripts/brain materialize
```

Writes to `BRAIN_DIR`:

| Artifact | Use |
|----------|-----|
| `brain.sqlite` | MCP queries (`/dist-brain`) |
| `graph.json` | compat export |
| `Home.md`, `*.md` module pages | human-readable wiki |
| `agent-context.md` | single-file agent briefing |
| `Changelog.md` | what changed this slice (`✏️` on ratified entities) |

Open in your editor: `BRAIN_DIR/Home.md`

**Grok prompt:** `materialize the brain` or `/brain-ops`

### Step 5 — Generate verification artifacts

```bash
./scripts/brain generate
# or individually:
./scripts/brain stubs
./scripts/brain gherkin
```

| Output | Purpose |
|--------|---------|
| `tests/generated/test_contract_verification.py` | pytest stubs from `@raises` / `@returns` |
| `tests/generated/features/*.feature` | BDD from `@intent` / `@feature` |
| `tests/generated/test_flag_matrix.py` | on/off per `@flag` (if flags exist) |

**Stub behavior (legacy):** unimplemented bodies use **`pytest.skip`**, not `pytest.fail`.
Your app test suite can stay green while stub debt is visible:

```bash
poetry run pytest tests/ -q --no-cov
# → 90 passed, 24 skipped   (skipped = contract TODOs)
```

### Step 6 (optional) — Implement contract stubs

Scaffolds already exist. You are filling in skips, not writing tests from scratch.

**Grok prompts:**

- `Implement contract verification stubs for @feature articles`
- `Implement verification stubs for app/services/jwt.py`
- `/verification` — regenerate, implement, run contract tests

Run contract tests only:

```bash
poetry run pytest -m contract_verification -q
```

Implement a body → its skip becomes a pass.

### Step 7 — App health check

During incremental legacy work, this is your default pytest — **not** full `verify`:

```bash
poetry run pytest tests/ -q --no-cov
```

---

## What *not* to run (yet)

### `./scripts/brain verify` on a sparse repo

`verify` runs, in order:

1. **Full-repo** `check_metadata` — every public function under `BRAIN_SRC` must have `@intent`
2. `generate --check`
3. `pytest`

If you have ratified 12 of 93 symbols, step 1 fails with dozens of missing contracts.
**Expected** — not a bug in your slice.

Use **`verify`** when:

- adoption is far enough along that the full gate passes, or
- boy-scout / diff-scoped gate exists (roadmap), or
- you intentionally want a hard full-repo audit

**Incremental alternative:**

```bash
./scripts/brain status
./scripts/brain generate --check
poetry run pytest tests/ -q --no-cov
```

### Bare `pytest` after `generate` (before skip fix)

Generated stubs used to call `pytest.fail` and turn the whole run red. They now skip.
If you see `Failed: Implement @returns smoke test…`, regenerate:

```bash
./scripts/brain stubs
```

---

## `scripts/brain` command reference

| Command | When |
|---------|------|
| `infer <path>` | Start a legacy slice |
| `status` | After ratify — see % climb |
| `materialize` | Refresh sqlite + local wiki |
| `stubs` / `gherkin` / `generate` | After contract changes |
| `gate` | Full Tier-1 metadata (strict) |
| `verify` | Pre-merge / greenfield done predicate |

Config: `brain.conf` → `BRAIN_SRC`, `BRAIN_DIR`, `DIST_BRAIN_ENGINE`.

---

## Grok slash commands & prompts

| Intent | Slash | Plain prompt |
|--------|-------|----------------|
| Run toolchain | `/brain-ops` | `materialize the brain` |
| Query brain | `/dist-brain` | `what does the brain say about articles?` |
| Infer slice | `/brain-ops` | `infer app/services/comments.py` |
| Ratify | — | `approve all drafts as written` |
| Implement stubs | `/verification` | `implement contract stubs for @feature articles` |
| Coverage report | `/brain-ops` | `brain status` |

---

## Checkpoints (two “done” moments)

Do not collapse these:

| Checkpoint | Meaning | How you know |
|------------|---------|--------------|
| **Ratify done** | Contracts are truth in source | `status` % climbs; `materialize` Changelog shows `✏️` |
| **Verify done** | Executable proof matches contracts | skips → passes; `verify` green (when gate scope fits) |

During Track 1 legacy reassessment, **ratify done** per slice is sufficient progress.
Say explicitly:

- `ratify only` — metadata + brain, stubs may skip
- `ratify and implement verification stubs` — also Step 6

---

## Suggested slice order (RealWorld-style)

1. `app/services/*` — small helpers, clear boundaries (authentication, jwt, security, articles)
2. `app/api/dependencies/*` — guards and DI factories
3. `app/api/routes/*` — HTTP surface
4. `app/db/repositories/*` — persistence
5. migrations / settings / error handlers last (or policy-exempt later)

One module per session is a good pace. `status` is your coverage bar.

---

## Optional metadata after ratify

Forgot `@feature` on an already-ratified function? Add one line to the docstring —
no re-inference required:

```python
"""
@intent ...
@feature articles
@provenance status: verified
...
"""
```

Then `materialize` + `generate`. `@feature` is not enforced by Tier-1 gate (unlike `@flag`,
which must exist in `flags.yml`).

---

## Publishing to GitHub wiki

Local `BRAIN_DIR` **is** the wiki content. Publishing syncs that folder to
`<your-repo>.wiki.git` on merge to `main` (see `wiki.yml` + `WIKI_TOKEN`).

Until then: local loop is complete with `materialize` + `status` + MCP on `brain.sqlite`.

---

## Roadmap (workflow gaps)

| Gap | Workaround today |
|-----|------------------|
| Boy-scout gate (touched files only) | Skip `verify`; use `status` + slice ratify |
| `verify` warns on low coverage | Read full gate failure as “81% still legacy” |
| Stub debt in `status` | Count skips in pytest summary |
| Track 2 library lift | Separate packet — see homeroom `library-lift-blast-radius.md` |

---

## Quick copy-paste session (happy path)

```bash
cd /path/to/your-repo

# slice
./scripts/brain infer app/services/articles.py
# → review inference-queue.md → ratify in editor or via Grok

./scripts/brain status
./scripts/brain materialize
./scripts/brain generate
poetry run pytest tests/ -q --no-cov

# optional: implement stubs for this feature
# → Grok: "implement contract stubs for @feature articles"
# → poetry run pytest -m contract_verification -q
```

Repeat until `status` shows the coverage you want before enabling full CI gate / `verify`.