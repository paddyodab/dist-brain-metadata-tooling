---
name: feature
description: >
  Contract-first feature workflow for distributed-brain repos. Turn the agreed plan
  into metadata contracts (@intent, @param, @returns, @raises, @feature, @flag),
  get approval, then implement to them. Use when building a feature, adding public
  functions, or when the user runs /feature.
metadata:
  short-description: "Contract-first feature capture"
---

# Contract-First Feature

You are building a feature in this repo with the engineer. **Metadata is as
important as the code** — it feeds the Tier-1 gate and the wiki. The plan you and
the engineer agreed on already contains the intent; capture it as contracts
*at that moment*, don't reconstruct it later.

The core move: the "here's my plan, do you agree?" checkpoint becomes a
**contract checkpoint**. Approving the contracts *is* approving the plan.

## Steps

1. **Source the intent — don't invent it.** Use what you and the engineer agreed
   in this conversation (and any ticket they named). If the plan is unclear on
   *why* a function exists or what it guarantees, ask before coding.

2. **Draft the contracts first, before the bodies.** For every public function
   you'll add or change, write the docstring contract and show it for approval
   *before* writing the implementation:
   - `@intent` — the guarantee / why, taken from the agreed plan
   - `@param` (every parameter) / `@returns` (if it returns a value) /
     `@raises` (every exception it can raise, including ones propagated from callees)
   - `@feature <name>` — the feature this implements
   - `@flag <flag>` — the flag that gates it, if any

3. **Resolve metadata gaps by asking — never guess:**
   - "What feature name should this belong to?" (if not already decided)
   - "Is this behind a feature flag? If so, what's its default and owning team?"
   - If it introduces a **new** flag, add it to `flags.yml` (description / default /
     owner) in the same change — the gate rejects an `@flag` that isn't registered.

4. **Present the contracts for approval.** "Here are the contracts I'll implement
   to — agree?" Approving the contracts == approving the plan.

5. **Implement to the approved contracts.** The contract is the spec.

6. **Generate verification stubs** from the approved contracts (before or right
   after implementation):

   ```bash
   python3 /path/to/dist-brain-metadata-tooling/engine/generate_verification.py --root .
   ```

   This writes `tests/generated/test_contract_verification.py` — one `@raises` test
   per declared exception, plus `@returns` smoke tests. Show new stubs for approval;
   implement any that are still `pytest.fail(...)`.

7. **Verify — the long-running checkpoint.** Not done until all pass:

   ```bash
   python3 .../engine/check_metadata.py --root .
   python3 .../engine/generate_verification.py --root . --check
   PYTHONPATH=src pytest -q
   ```

   Or run `/verification` for the full loop. A failure means code, contract, or
   tests disagree — fix and re-run until green.

## Brain context

If the `dist-brain` MCP server is enabled, call `dist_brain__overview` first to
orient, then `dist_brain__search` or `dist_brain__get_entity` for related entities
before changing contracts. Cite stable entity ids in your summary.

## Why

The plan-approval conversation is where intent is richest and freshest. Capturing
it as contracts *then* keeps the metadata as true as the code. The gate keeps them
in lockstep; the materializer projects them into the wiki on every merge.