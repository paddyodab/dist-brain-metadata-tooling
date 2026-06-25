# Constraint ADRs — house rules that gate, not just record

**Status:** canonical · **Last updated:** 2026-06-25

How to turn a forward-looking architecture decision into a premise agents reason within —
and, when a check is feasible, a gate that fails CI when the constraint regresses.

## Two kinds of ADR

Today's ADRs are **record ADRs** — retrospective facts ("`resolve()` does not record
clicks"): context → decision → consequences, dated, true forever because they describe a
past choice. They don't rot, and they need no enforcement.

"Must use a monorepo" or "every inter-service boundary has a Pact" are a different animal:
**constraint ADRs** — *prescriptive premises* that shape all future work. They have two
properties a record ADR doesn't:

1. **They're a premise for future work.** "Should we split this into its own repo?" is a
   dead question if a monorepo ADR is accepted — the agent should surface that, not
   entertain it.
2. **They can be enforceable.** "Must use Pact" implies *every new boundary has a pact*,
   which is checkable.

## The ADR fidelity ladder

Mirrors the metadata ladder (colocated → gated):

| Rung | State | Effect |
|---|---|---|
| **0** | Prose in `decisions/` | A human can read it. Agents miss it. |
| **1** | Materialized into the brain (`list_decisions`) | Agents *read* it at orientation. |
| **2** | Injected as a **premise** into grilling / `/feature` | Agents *reason within* it; flag violations, offer supersession. |
| **3** | Backed by a **gate** | CI *fails* when a change violates it. The constraint can't regress. |

Record ADRs stop at rung 1. Constraint ADRs reach rung 2 always, and rung 3 whenever a
check is feasible — don't fake rung 3.

## Authoring a constraint ADR

Keep ADRs in `decisions/`; add frontmatter so the materializer and gate can act on them:

```yaml
---
id: 0007
title: All inter-service contracts use Pact
status: accepted            # accepted | superseded | proposed  (only accepted is enforced)
kind: constraint            # record | constraint   ← the new axis (default: record)
enforcement: deterministic  # advisory | semantic | deterministic
gate: checks/adr_0007_pact.py   # required iff enforcement: deterministic
applies_to: any cross-service boundary
---
## Context / Decision / Consequences   (unchanged — Nygard shape)
```

- `kind: record` (or no frontmatter at all) → behaves exactly as before. The frontmatter is
  optional and additive; a bare record ADR keeps its historic node shape.
- `enforcement: advisory` → rung 2: a premise, no gate. (`monorepo` is usually this.)
- `enforcement: semantic` → rung 3 via an LLM reviewer (freshness-review's sibling): "does
  this diff violate the ADR's intent?" Reported by the deterministic runner as an advisory
  notice; the actual check is **intended for `/code-review` (not yet wired)** — so a semantic
  constraint isn't gated anywhere today. ("prefer composition over inheritance" is semantic
  at best.)
- `enforcement: deterministic` → rung 3 via the `gate:` script (`pact` is a clean one:
  pact files exist per boundary).

The node id stays filename-based (`decision:<stem>`) — the frontmatter `id` is recorded in
`facts` but never changes the id, so existing `decision:*` references keep working.

## The `gate:` contract (deterministic)

`check_constraints` runs each accepted deterministic constraint's gate:

- Invoked from the **repo root**, with `GITHUB_WORKSPACE` set to the root. `*.py` gates run
  under the current interpreter; anything else is executed directly (must be executable).
- It's a **whole-repo invariant** check, not diff-scoped (a constraint holds for the whole
  tree, not just the diff).
- **Exit 0 = constraint holds; nonzero = violated** (print the offenders to stdout/stderr).
- **Fail-closed:** a missing gate script — or a `deterministic` ADR with no `gate:` — is a
  failure, not a pass. A constraint that claims enforcement but can't run is broken.

See [`../examples/constraint-adr/`](../examples/constraint-adr/) for a runnable example:
ADR-0007 (Pact, deterministic) + its gate, plus an advisory monorepo ADR.

## Running it

```bash
scripts/brain constraints          # enforce accepted constraints; list the house rules
# or directly:
python3 engine/check_constraints.py --root .
```

Advisory and semantic constraints are *reported* (so the engineer sees the house rules) but
never fail the runner. Only a violated deterministic gate — or a malformed/​unrunnable one —
exits nonzero.

## Where they show up

- **Brain / MCP:** `dist_brain__list_decisions(kind="constraint")` returns the house rules
  with their `enforcement` and `applies_to`. `overview()` tags every decision with its kind.
- **agent-context.md / Decisions.md:** accepted constraints render under **House rules**
  (with enforcement + applies_to + gate), split out from the retrospective record ADRs.
- **`/feature`:** consults the constraints *first* as premises — stay within them or propose
  superseding the ADR, never silently break one.

## CI wiring (deferred)

`check_constraints` is meant to run alongside `check_metadata` in the gate workflow. Wiring
it into `gate.yml` / `action.yml` is tracked separately (it composes with — does not collide
with — the boy-scout `--since` work). The engine and CLI are done; the workflow hook is the
remaining step.
