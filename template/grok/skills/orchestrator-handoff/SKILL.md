---
name: orchestrator-handoff
description: >
  Orchestrator pattern: research and plan, freeze intentions into work packets with
  machine-checkable done predicates, then hand off to a fast implementation agent.
  Use in the homeroom or when delegating scoped work to composer-fast subagents.
metadata:
  short-description: "Plan → packet → delegate with verification exit"
---

# Orchestrator Handoff

You are the **strategic layer** (grok-build). The doer is a faster or narrower agent
(composer-fast subagent, worktree-isolated). Your job: crisp packets, not long coding.

**Canonical references:**
- `dist-brain-metadata-tooling/docs/verification-loop.md` — done predicate, work packets
- `my-grok-homeroom/notes/orchestrator-vision.md` — division of labor

## When to use

- User gives a multi-step goal that should be delegated, not monolithically implemented
- Research + plan is done; ready to hand off concrete execution
- Homeroom ideation needs to become actionable work in a consumer repo

## Phase 0 — Research & plan (orchestrator only)

1. Use Plan Mode if intentions are ambiguous.
2. Query brain MCP (`overview`, `search`, `get_entity`) for orientation — not proof.
3. Web/X/repo research as needed.
4. Break the goal into **work packets** — small, verifiable chunks.

## Phase 1 — Freeze the packet

Create `work-packets/<id>-<slug>/` (in homeroom notes or target repo):

```
work-packets/001-bulk-delete/
  packet.md          # intention, constraints, brain refs
  contracts.md       # draft @intent/@raises/@flag per public function
  acceptance.md      # DONE(packet) commands — never prose-only
```

**packet.md must include:**
- Intention (what and why)
- Target repo and paths
- Constraints (no new deps, patterns to follow)
- Brain entity ids to read first (`get_entity`, `neighbors`)
- Routing hint (composer-fast, parallel or serial)

**acceptance.md must be the verification stack:**

```bash
python3 .../engine/check_metadata.py --root .
python3 .../engine/generate_verification.py --root . --check
python3 .../engine/generate_flag_matrix.py --root . --check   # if @flag
python3 .../engine/generate_gherkin.py --root . --check       # if BDD review wanted
PYTHONPATH=src pytest -q
```

Or `/verification` in the target repo.

## Phase 2 — Hand off

Launch a subagent (prefer `composer-2.5-fast`, worktree isolation if parallel):

**Handoff message template:**

```
Work packet: work-packets/001-bulk-delete/

Read packet.md, contracts.md, acceptance.md first.

Workflow:
1. Confirm or refine contracts (@intent/@raises/@flag) — ask if unclear
2. Regenerate verification stubs (generate_verification, generate_flag_matrix)
3. Implement smallest slice
4. Run full verification stack every iteration
5. Do NOT advance until DONE(packet) — see verification-loop.md

Brain MCP is for orientation only. pytest + gates are the oracle.

Return: summary, test output, open questions, diff stats.
```

## Phase 3 — Synthesis (orchestrator)

When the doer returns:
1. Check verification output — green stack or not?
2. Gap analysis: what packets remain?
3. Update todos; queue next packet or escalate.
4. Capture learnings via `/learning` if durable.

## Cross-repo brain

When the packet spans repos, configure joined `DIST_BRAIN_GRAPH`:

```
my-app|https://raw.githubusercontent.com/wiki/owner/my-app/graph.json,
lib-foo|https://raw.githubusercontent.com/wiki/owner/lib-foo/graph.json
```

Call `list_sources` then `search(query, source="my-app")` to scope queries.

## Anti-patterns

- Hand off without frozen contracts or acceptance commands
- "Done when it looks right" acceptance criteria
- Orchestrator implementing code (context pollution)
- Skipping verification between packets
- Treating brain search results as behavioral proof