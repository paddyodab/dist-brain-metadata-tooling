---
description: Contract-first IaC — capture required tags + intent before writing any CloudFormation/Terraform resource. The agent asks, so you don't forget.
---

You are crafting infrastructure (CloudFormation or Terraform). The IaC contract is
**not** a docstring — it's a **required tag set + intent**. Forgetting tags is the
recurring pain (broken cost allocation, no owner, audit flags), so the whole point
of this command is: **ask for the tags up front, before writing the resource.**

## Steps

1. **Source the required tags — ask, don't guess.** The repo's `tag-policy.yml`
   lists the required keys (e.g. Owner / Environment / CostCenter / Service). For
   each, get the *value* from the engineer if it isn't already determined:
   - "Who owns this — which team/Owner tag?"
   - "Which Environment (prod/staging/dev)?"
   - "What CostCenter does this bill to?"
   - "Which Service does it belong to?"

2. **Source the intent.** One line on *why* this resource exists (what it's for),
   from the agreed plan.

3. **Prefer applying tags by construction.** Don't hand-tag every resource:
   - **Terraform:** a provider `default_tags { tags = {...} }` block (or a shared
     tagging module) applies the required set to every resource automatically.
   - **CloudFormation:** stack-level `Tags` at deploy, or a shared macro/module.
   Per-resource tags are the fallback when a resource needs to differ.

4. **Write intent into a parseable field** (so it reaches the wiki + agent context):
   - **CloudFormation:** `Metadata: { Intent: "..." }` on the resource.
   - **Terraform:** a `# @intent ...` comment in the resource block.

5. **Present the resource(s) for approval** — tags + intent shown — before
   applying. This is the "do you agree?" checkpoint for infra.

6. **Verify** with the required-tags gate (CI runs it on every PR; locally,
   `python3 .../engine/check_tags.py --root .`). A taggable resource missing any
   required key fails the build.

## Why this is its own command

Code's contract is behavioral (`/feature` captures intent as docstrings). Infra's
contract is operational policy (tags) that also rides to production and is
drift-detectable. Different contract → different front door. When a `/feature`
plan includes IaC, follow these tag-capture rules for the infra part.
