---
description: Triage a learning by its half-life and route it to a self-maintaining home (code/test, ADR, or pointer) — never a rotting wiki.
---

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
   | **A how-to** ("to do X, run/configure Y") | **code/IaC** — a script, Make target, or Terraform/CFN module (with the metadata/tag contract) | Execution is the freshness test: it works or it fails in CI. |
   | **A claim** ("X is faster", "this breaks under load Y") | **a test or benchmark** | Re-runnable; CI re-verifies it every build. |
   | **A decision** ("we chose A over B because Z", a postmortem) | **an ADR** in `decisions/` | Dated and immutable — it records a past decision, so it never goes stale. |
   | **A volatile external fact** ("the vendor console flow is…", "their API returns…") | **a pointer, not stored truth** — link the authoritative source; if it must be cached, attach a freshness loop that re-verifies it | The truth lives at the source; storing a snapshot is the rot. |

3. **Do the routing now, not later.** Draft the artifact (the script, the test,
   the ADR, or the pointer) and show it for approval. For code/IaC and ADRs, the
   normal contract/gate applies — write the `@intent`, the required tags, the ADR
   context→decision→consequences.

4. **Refuse to store volatile facts as durable truth.** If the learning is row 4
   and there's no authoritative source to point at, say so — capturing it as
   "knowledge" just manufactures a future stale doc. A pointer plus "re-check at
   use" is the honest answer.

## Capture-now, route-later (optional)

If the half-life isn't clear in the moment, append the raw note to a
`learnings-inbox.md` **queue** (not a store) and move on. The inbox is meant to
trend empty: a later `/learning` pass drains each item into its real home above.
Don't let the inbox become the rotting wiki this command exists to prevent.

## Why

Knowledge isn't kept by writing it down — it's kept by routing it into something
that re-checks itself. Code runs, tests fail, ADRs are dated, sources are
authoritative. A flat "learnings" doc is none of those, which is why it rots.
