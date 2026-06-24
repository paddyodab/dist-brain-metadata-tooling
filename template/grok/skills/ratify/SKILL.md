---
name: ratify
description: >
  Grill-to-ratify a legacy inference queue: turn infer_intent's draft @intent contracts
  into verified ones by interviewing the engineer on the shaky drafts instead of
  rubber-stamping. Use after `scripts/brain infer`, when the user says "ratify",
  "review the inference queue", or "grill me on these inferences".
metadata:
  short-description: "Grill-to-ratify legacy inference drafts"
---

# Grill-to-Ratify

`infer_intent.py` drafts `@intent` contracts for legacy code into `inference-queue.md`.
Those drafts are **inferred, not true**. "Ratify all" is the failure mode: it launders a
machine guess into source-of-truth. This skill ratifies *deliberately* — recovering real
meaning before flipping `inferred → verified`.

**The bar: an `@intent` must say something the signature does not.** A guarantee, an
invariant, a *why*, a non-obvious failure mode. If it only restates the name, it is
**sediment** — meaningless metadata that costs tokens and tells the next reader nothing.

## Run it

Work from `inference-queue.md` (run `scripts/brain infer <path>` first if it's missing).
Take **one symbol at a time** — asking about a whole module at once is bewildering. For
each draft, sort it into one of three branches.

### Branch 1 — Sediment (the draft just echoes the name)

The draft restates the symbol. `get_user` → "@intent Gets the user." `is_valid` →
"@intent Returns whether it is valid." This passes no-op: it adds nothing the signature
already says. **Do not ratify it.** Meaning has to come from somewhere — recover it:

1. **Try the code first (cheapest).** Read the body, its callers, and the git log lines the
   queue already gathered. Is there a real guarantee hiding? — "rejects an already-taken
   seat", "returns results sorted by rank", "idempotent: safe to call twice", "raises on the
   empty case rather than returning a default". If you find it, draft *that* and confirm.
2. **If the code doesn't reveal it, grill the engineer** — the why often lives only in their
   head: "`get_user` — does it raise when the user is missing, or return None? Is the result
   cached/authoritative? Why does this exist separately from `load_user`?"
3. **If there is genuinely nothing to say** — a trivial pure accessor with no invariant — say
   so and *skip it*. A missing contract is honest; a sediment contract is a lie that reads
   as documented. Don't manufacture meaning to fill a slot.

### Branch 2 — Shaky (evidence conflicts or the intent is a guess)

The draft asserts a behavior the evidence doesn't settle, or the signals disagree. **Grill
the specific conflict**, one question at a time, with your recommended answer attached:

> "`charge()` — the git log says *'fix double-charge'*, but two call sites treat it as
> idempotent. Does it dedupe internally, or must the caller guard? (I'd guess it dedupes —
> the fix commit suggests it now does.)"

The engineer's answer *is* the `@intent`. Capture it verbatim-ish, sharpen to a guarantee.

### Branch 3 — Clear (code, callers, and git agree, and the draft says something real)

Propose the draft, note why you trust it, get a one-word confirm, ratify. Don't waste the
engineer's attention interrogating what's obvious — spend it on Branches 1 and 2.

## Ratifying (all branches)

When a draft is confirmed, write the contract into the docstring and flip provenance:

```python
"""
@intent <the recovered guarantee / why — NOT a restatement of the name>
@param <each parameter>
@returns <if it returns a value>
@raises <every exception, including propagated ones a lexical scan misses>
@feature <optional grouping>
@provenance status: verified
ratified_at: <date>
"""
```

Then hand off to the toolchain: `scripts/brain materialize` (brain + wiki) and
`scripts/brain generate` (verification stubs). `scripts/brain status` shows the coverage
climb. Leave anything you didn't ratify marked `inferred` — it's revisited on next touch.

## Don't

- **"Ratify all."** That's the thing this skill exists to prevent.
- **Invent meaning** to make a draft look complete. Meaning comes from the code or the
  engineer — never from you filling the gap with plausible prose.
- **Ratify sediment.** A contract that echoes the name is worse than no contract: it reads
  as documented while saying nothing.
- **Batch questions.** One symbol, one question, wait.

## Why

Inference gets you to rung 0→1 cheaply, but a queue of name-echoing drafts is fake coverage:
`status` climbs while the brain learns nothing. Grilling — and the no-op bar — is what turns
a guess into a guarantee the next agent (or human) can actually rely on.
