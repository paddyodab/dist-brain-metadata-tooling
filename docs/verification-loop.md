# The verification loop — why long-running agents can actually finish

**Status:** canonical · **Last updated:** 2026-06-20

This is the soul of the distributed-brain **execution** capability — not the brain
MCP, not the wiki, not the gates alone. Those make knowledge trustworthy; **this**
is what lets an agent run for a long time without lying about being done.

---

## The insight everybody is circling

Goal commands, loop sessions, autonomous agents — the conversation is about *duration*.
But duration isn't the hard part. **Knowing when you're finished** is.

Long runs fail when the agent stops on vibes: "implemented," "looks right," "tests
can come later." The fix isn't more autonomy or a bigger context window. It's a **cheap,
deterministic done predicate** the agent can run every iteration without asking you.

Distributed brain already has the spec layer: colocated `@intent` / `@raises` contracts,
Tier-1 gates, materialized read models. Verification closes the loop:

```
intentions → contracts → generated tests → pytest green
```

Meaning, definition, and proof stay on the same WAL.

---

## The done predicate

A work packet is **not complete** until this stack passes:

```
DONE(packet) :=
  check_metadata.py          passes   (Tier-1: structure matches contract)
  AND generate_verification --check   passes   (stubs match current contracts)
  AND pytest -q                       passes   (behavior matches contracts)
  AND (pre-merge) /freshness-review   PASS     (Tier-2: prose still true)
```

No green stack → keep working. No exceptions for "I'll fix tests later."

---

## Work packets

Before a long run, freeze intentions into **packets** — small, verifiable chunks:

```
packet-001: bulk-delete endpoint
  contracts:  delete_links(...) — @intent, @raises, @flag draft
  acceptance: DONE(packet) as defined above
  brain refs: get_entity(flag:enable_link_deletion), neighbors(...)
```

- **Contracts** are the spec (approved before or at the start of the packet).
- **Acceptance** is always the verification stack — never prose like "feature works."
- **Brain refs** are orientation only; they are not the oracle.

One packet at a time. Green stack → commit → next packet.

---

## The loop (four phases)

### Phase 0 — Intake (once)

You supply intentions. The agent turns them into contract drafts and a packet queue.
If intentions are already crisp, they *are* the contracts — but they must be written
down in `@intent` form before implementation starts.

### Phase 1 — Contract checkpoint (per packet)

1. Draft or confirm contracts for every public function in the packet.
2. Run `generate_verification.py --root .` — materialize test obligations.
3. Review new/changed stubs in `tests/generated/`.

Every `@raises` gets a named test. Every `@returns` gets a smoke test. The agent now
knows what "prove it" means in executable terms.

### Phase 2 — Implement loop (the long-running part)

```
repeat until DONE(packet):
    implement smallest slice (code + any stub bodies still failing)
    run verification stack (gate → --check → pytest)
    if fail:
        read which layer failed and which test
        fix code, or fix contract (only if intention truly changed — re-confirm)
    if pass:
        mark packet complete
```

**Run pytest every iteration.** Gate and `--check` are fast; run them too. Do not
batch five packets and test once at the end — failures become archaeology.

### Phase 3 — Between packets

- Regenerate verification if contracts changed.
- Query brain MCP to orient (`overview`, `get_entity`) before the next packet.
- Commit per packet: contracts + code + `tests/generated/` + green pytest.

---

## What each layer catches

| Layer | Question | Loop behavior |
|---|---|---|
| **Tier-1 gate** | Are contracts structurally valid? | Fix contract or code; cannot skip |
| **`--check`** | Do generated stubs match contracts? | Regenerate, then implement |
| **pytest** | Does behavior match contracts? | Fix implementation |
| **Tier-2 freshness** | Does prose still match code? | Fix `@intent` or code before merge |

In a long session, **pytest is the inner loop**. Gates are guardrails you run every
time because they're cheap and deterministic.

---

## What brain and LSP do (and don't)

| Tool | Role in long runs |
|---|---|
| **Brain MCP** | Cheap orientation — what exists, what's gated, ADRs. Saves tokens. **Not the oracle.** |
| **LSP** | Navigate to definitions and references. **Not the oracle.** |
| **Verification stack** | **The oracle.** Only this decides done. |

```
start packet → brain/LSP orient
            → implement
            → verification stack
            → done? next packet : fix and repeat
```

---

## What not to do

- Stop on "code looks right" without a green stack.
- Skip regenerating stubs after contract edits.
- Hand-write tests that don't trace to `@raises` (they'll drift from the spec).
- Edit `tests/generated/` structure by hand (regenerate from contracts).
- Batch many packets before running pytest.
- Treat brain queries as proof that behavior is correct.

---

## Commands (local and CI)

```bash
# Materialize test obligations from contracts
python3 engine/generate_verification.py --root .

# Full checkpoint
python3 engine/check_metadata.py --root .
python3 engine/generate_verification.py --root . --check
PYTHONPATH=src pytest -q
```

In Grok: `/verification` runs this loop. `/feature` ends with it.

GitHub Actions: `gate` + `verify` (`--check`) + `tests` (`pytest`) jobs — same
semantics, split across jobs for clarity.

---

## Why this generalizes

- **Greenfield:** `/feature` at plan time → contracts → stubs → implement → verify.
  Team + GHA enforce the habit; brain grows at the velocity of real work.
- **Legacy:** Brain has gaps (rung 0). LSP + grep for cold code; verification still
  applies on *touched* functions — boy-scout rule, gate-enforced. **Walkthrough:**
  [`legacy-adoption-workflow.md`](legacy-adoption-workflow.md) (infer → ratify →
  `scripts/brain`; stub skips; incremental vs full `verify`).
- **Long-running / goal sessions:** The queue is packets; the stop condition is
  `DONE(packet)`; the session ends when the queue is empty and every packet green.

The missing piece for autonomous duration was never "try harder." It was **make done
machine-checkable** — and wire intentions into that check at write time, not review time.

---

## Related

- [`SETUP.md`](../SETUP.md) — wiring a consumer repo
- [`README.md`](../README.md) — tooling overview
- [`code-samples-with-ai-metadata` decisions](https://github.com/pdabney/code-samples-with-ai-metadata/tree/main/decisions) — ADRs 0001–0009 (the *why* behind contracts and gates)
- Grok skills: `/feature`, `/verification`, `/freshness-review`, `/dist-brain`