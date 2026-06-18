# Contributing — metadata is part of "done"

A change isn't done until its **metadata** is. Every public function carries a
colocated contract; the Tier-1 gate (the dist-brain metadata gate) enforces it in
CI, and the materializer projects it into the wiki on every merge. Stale or
missing metadata is a build failure.

## Definition of Done (metadata)

For every public function you add or change:

- [ ] **`@intent`** — what it guarantees and *why*
- [ ] **`@param`** for every parameter
- [ ] **`@returns`** if it returns a value
- [ ] **`@raises`** for every exception it can raise — *including propagated ones*
- [ ] **`@feature <name>`** if it implements a user-facing feature
- [ ] **`@flag <flag>`** if it's gated — and the flag exists in `flags.yml`
      (with `description` / `default` / `owner`)
- [ ] the metadata gate passes (CI runs it on every PR)

## Capture it at plan time, not after

Use **`/feature`** (`.claude/commands/feature.md`). The plan you and the agent
agree on *is* the intent — write it as contracts, approve the contracts, implement
to them. Reconstructing intent after the fact is how it drifts.

## Decisions go in `decisions/`

If a change embodies a cross-cutting decision, add or supersede an ADR there.
