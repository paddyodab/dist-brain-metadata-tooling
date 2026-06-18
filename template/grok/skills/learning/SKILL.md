---
name: learning
description: >
  Triage a learning by its half-life and route it to a self-maintaining home
  (code/IaC, test, ADR, or pointer) — never a rotting wiki. Use when the user
  captured a learning, figured something out, or runs /learning.
metadata:
  short-description: "Route learnings by half-life"
---

# Route a Learning

A "learning" is something you just figured out. Most learnings rot if you write
them into a doc and walk away. The job of this command is **not** to store the
learning — it's to **route** it to a home where it stays true on its own. Ask one
question: *is this executable, decidable, or volatile?*

## Steps

1. **Take the learning** from the engineer (or the conversation). Restate it in
   one sentence so you both agree what it is.

2. **Classify it** by half-life and route accordingly — pick exactly one:

   | The learning is… | Route to | Why it stops rotting |
   |---|---|---|
   | **A how-to** ("to do X, run/configure Y") | **code/IaC** — script, Make target, or Terraform/CFN module (with metadata/tag contract) | Execution is the freshness test: it works or fails in CI. |
   | **A claim** ("X is faster", "breaks under load Y") | **a test or benchmark** | Re-runnable; CI re-verifies every build. |
   | **A decision** ("chose A over B because Z", postmortem) | **an ADR** in `decisions/` | Dated and immutable — records a past decision, never goes stale. |
   | **A volatile external fact** (vendor console flow, API behavior) | **a pointer, not stored truth** — link the authoritative source; freshness-loop only if cached | Truth lives at the source; storing a snapshot is the rot. |

3. **Do the routing now, not later.** Draft the artifact (script, test, ADR, or
   pointer) and show it for approval. For code/IaC and ADRs, the normal
   contract/gate applies — write `@intent`, required tags, ADR
   context→decision→consequences.

4. **Refuse to store volatile facts as durable truth.** If the learning is row 4
   and there's no authoritative source to point at, say so — capturing it as
   "knowledge" manufactures a future stale doc.

## Capture-now, route-later (optional)

If the half-life isn't clear, append the raw note to `learnings-inbox.md` **queue**
(not a store). The inbox must trend empty — drain it on a later `/learning` pass.
Don't let the inbox become the rotting wiki this command exists to prevent.

## Why

Knowledge is kept by routing it into something that re-checks itself. Code runs,
tests fail, ADRs are dated, sources are authoritative. A flat "learnings" doc is
none of those.