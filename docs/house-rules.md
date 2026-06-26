# House rules — forward-looking constraints

**Status:** canonical · **Last updated:** 2026-06-26

How to turn a forward-looking architecture decision into a premise agents reason within —
and, when a check is feasible, a gate that fails CI when the constraint regresses.

House rules live in `house-rules/*.yml`. They are **separate** from record ADRs in
`decisions/*.md`, which stay pure Nygard (retrospective, no enforcement).

## Two kinds of written rule

- **Record ADRs** (`decisions/*.md`) — retrospective facts ("`resolve()` does not record
  clicks"): context → decision → consequences, dated, true forever because they describe a
  past choice. They don't rot, and they need no enforcement.
- **House rules** (`house-rules/*.yml`) — *prescriptive premises* that shape all future
  work. They have two properties a record ADR doesn't:
  1. They're a premise for future work.
  2. They can be enforceable.

## The rule fidelity ladder

| Rung | State | Effect |
|---|---|---|
| **0** | Prose in `house-rules/` or `decisions/` | A human can read it. Agents may miss it. |
| **1** | Materialized into the brain (`list_house_rules`) | Agents *read* it at orientation. |
| **2** | Injected as a **premise** into grilling / `/feature` | Agents *reason within* it; flag violations, offer supersession. |
| **3** | Backed by a **gate** | CI *fails* when a change violates it. The rule can't regress. |

Record ADRs stop at rung 1. House rules reach rung 2 always, and rung 3 whenever a check
is feasible — don't fake rung 3.

## Authoring a house rule

Create `house-rules/<name>.yml`:

```yaml
id: 0007
rule: All inter-service contracts use Pact
rationale: |
  As the system splits into services, each cross-service call is a contract. Without a
  machine-checked contract, a producer can change a payload and break a consumer with no
  signal until runtime. We want the boundary, not just the code, to be verifiable.
enforcement: deterministic
gate: checks/adr_0007_pact.py
applies_to: any service under services/ (every cross-service boundary)
status: accepted
```

Fields:

- `id` — stable rule id (optional, used for human reference)
- `rule` — short, prescriptive title (required)
- `rationale` — the "why" (block scalar `|` or inline string)
- `status` — `accepted` | `superseded` | `proposed` (only `accepted` is enforced)
- `enforcement` — `advisory` | `semantic` | `deterministic`
- `gate` — required iff `enforcement: deterministic`; repo-relative path to the gate script
- `applies_to` — optional scope hint for humans

Effects:

- `enforcement: advisory` → rung 2: a premise, no gate. (`monorepo` is usually this.)
- `enforcement: semantic` → rung 3 via an LLM reviewer. Reported by the deterministic
  runner as an advisory notice; the actual check is intended for `/code-review`.
- `enforcement: deterministic` → rung 3 via the `gate:` script.

The node id is filename-based (`house-rule:<stem>`) — the frontmatter `id` is recorded in
`facts.rule_id` but never changes the node id, so existing references stay stable.

## The `gate:` contract (deterministic)

`check_constraints` runs each accepted deterministic rule's gate:

- Invoked from the **repo root**, with `GITHUB_WORKSPACE` set to the root. `*.py` gates run
  under the current interpreter; anything else is executed directly (must be executable).
- It's a **whole-repo invariant** check, not diff-scoped.
- **Exit 0 = rule holds; nonzero = violated** (print the offenders to stdout/stderr).
- **Fail-closed:** a missing gate script — or a `deterministic` rule with no `gate:` — is
  a failure, not a pass.

See [`../examples/constraint-adr/`](../examples/constraint-adr/) for a runnable example:
`house-rules/pact.yml` (deterministic) + its gate, plus `house-rules/monorepo.yml` (advisory).

## Running it

```bash
scripts/brain constraints          # enforce accepted house rules; list them
# or directly:
python3 engine/check_constraints.py --root .
```

Advisory and semantic rules are *reported* but never fail the runner. Only a violated
deterministic gate — or a malformed/unrunnable one — exits nonzero.

## Where they show up

- **Brain / MCP:**
  - `dist_brain__list_house_rules()` returns the active house rules with enforcement and
    `applies_to`.
  - `dist_brain__list_decisions()` returns record ADRs only.
  - `overview()` reports `house_rules` and `decisions` separately.
- **agent-context.md / Decisions.md:** accepted house rules render under **House rules**
  (with enforcement, applies_to, gate), split out from the retrospective record ADRs.
- **`/feature`:** consults the house rules *first* as premises — stay within them or propose
  superseding the rule, never silently break one.

## CI wiring (deferred)

`check_constraints` is meant to run alongside `check_metadata` in the gate workflow. Wiring
it into `gate.yml` / `action.yml` is tracked separately (it composes with — does not collide
with — the boy-scout `--since` work). The engine and CLI are done; the workflow hook is the
remaining step.

## Relationship to ADRs

A house rule often starts as a record ADR ("we decided X"). Once it becomes a
forward-looking constraint, move the prescriptive content to `house-rules/*.yml` and keep
the original ADR as a pure record with a pointer to the new house-rule file. This keeps
`decisions/` as history and `house-rules/` as the enforceable rulebook.
