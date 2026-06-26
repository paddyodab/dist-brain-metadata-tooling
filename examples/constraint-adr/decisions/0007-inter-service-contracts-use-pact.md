# 7. All inter-service contracts use Pact

**Status:** Accepted · 2026-06-25

## Context

As the system splits into services, each cross-service call is a contract. Without a
machine-checked contract, a producer can change a payload and break a consumer with no
signal until runtime. We want the boundary, not just the code, to be verifiable.

## Decision

Every service exposes and consumes contracts via **Pact**. Concretely: every directory
under `services/` carries a `pacts/` directory holding its contract artifacts. A new
service with no `pacts/` is a violation, not a "todo".

## Consequences

- A new boundary cannot ship without a contract — the house-rule gate
  (`checks/adr_0007_pact.py`) fails CI when a service lacks `pacts/`.
- This is a forward-looking premise: `/feature` and grilling must treat "add a service"
  as implying "add its pacts/", and must not entertain contract-free boundaries.
- Superseding this rule requires flipping `status` to `superseded` in
  `house-rules/pact.yml` and adding a replacement — you cannot quietly drop the gate.
