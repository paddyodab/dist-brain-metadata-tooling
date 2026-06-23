---
name: brain-ops
description: >
  Run the local dist-brain toolchain via scripts/brain — materialize, infer legacy
  contracts, metadata gate, and generate verification/gherkin stubs. Use when the
  user runs /brain-ops, asks to materialize the brain, run the metadata gate, or
  regenerate contract artifacts without remembering engine paths.
metadata:
  short-description: "scripts/brain CLI for engine commands"
---

# Brain Ops (local toolchain)

Consumer repos ship `scripts/brain` — a bash wrapper over
`dist-brain-metadata-tooling/engine/*.py`. **Prefer this over raw python3 paths.**

Config (optional): copy `brain.conf.example` → `brain.conf` at repo root.

| Command | What it does |
|---------|----------------|
| `scripts/brain materialize` | `brain.sqlite` + `graph.json` → `BRAIN_DIR` |
| `scripts/brain infer <path>` | `inference-queue.md` for symbols missing `@intent` |
| `scripts/brain gate` | Tier-1 `check_metadata` |
| `scripts/brain gherkin` | Generate BDD features from `@intent` / `@feature` |
| `scripts/brain stubs` | Generate contract verification pytest stubs |
| `scripts/brain generate` | stubs + flags + gherkin |
| `scripts/brain verify` | gate + `--check` on all generators + pytest |
| `scripts/brain status` | **local coverage report** — intent % by module, queue backlog, wiki paths |

## When to use

- After ratifying contracts → `materialize` then point MCP at `BRAIN_DIR/brain.sqlite`
- After touching docstrings → `generate` (or `verify` before merge)
- Legacy slice → `infer app/services/foo.py`, engineer ratifies, then `materialize`
- User pasted a long `python3 .../engine/...` path → substitute `scripts/brain`

## Workflow shortcuts

**After any ratify slice — check progress locally (no GH/wiki wait):**
```bash
scripts/brain status
scripts/brain materialize
# open BRAIN_DIR/Home.md or agent-context.md in your editor
scripts/brain generate
```

**Pre-merge checkpoint (pairs with `/verification`):**
```bash
scripts/brain verify
```

**New legacy module:**
```bash
scripts/brain infer app/services/articles.py
# engineer approves queue → edit docstrings → materialize + generate
```

## If scripts/brain is missing

Fall back to engine with explicit `--src` (RealWorld uses `app`, not `src`):

```bash
python3 $DIST_BRAIN_ENGINE/materialize.py --root . --src app --brain /tmp/brain
```

Do not guess `...` paths — resolve `DIST_BRAIN_ENGINE` from `brain.conf` or sibling checkout.