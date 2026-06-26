# 8. Single monorepo

**Status:** Accepted · 2026-06-25

## Context

We want one place to change, one CI, one brain. A second repo fragments ownership and
breaks the cross-cutting graph.

## Decision

All code lives in this monorepo. "Should we split X into its own repo?" is a settled
question — the answer is no unless this house rule is superseded.

## Consequences

- This is an **advisory** house rule (rung 2): it has no cheap deterministic gate, so it
  is injected as a premise into grilling / `/feature`, which should surface it rather than
  entertain a split. It does not fail CI on its own.
