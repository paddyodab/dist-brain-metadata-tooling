---
name: verification
description: >
  Contract verification loop for long-running agent work. Regenerate pytest stubs
  from @intent/@raises, run tests, and treat green pytest + metadata gate as done.
  Use after /feature implementation, in goal/loop sessions, or when the user runs
  /verification.
metadata:
  short-description: "Contract → tests → pytest checkpoint"
---

# Contract Verification Loop

Long-running agents fail without **checkpoints**. Contracts say what must be true;
tests prove it. This skill is the done-ness gate.

**Canonical doc (read for goal/loop sessions):**
`dist-brain-metadata-tooling/docs/verification-loop.md` — the done predicate,
work packets, and what *not* to do in autonomous runs.

## When to use

- After `/feature` implementation (step 7)
- In a goal/loop session — run this each iteration before declaring progress
- When contracts changed — regenerate stubs first

## Steps

1. **Regenerate all verification artifacts** from current contracts:

   ```bash
   python3 /path/to/dist-brain-metadata-tooling/engine/generate_verification.py --root .
   python3 /path/to/dist-brain-metadata-tooling/engine/generate_flag_matrix.py --root .
   python3 /path/to/dist-brain-metadata-tooling/engine/generate_gherkin.py --root .
   ```

2. **Implement any new stubs** — generated tests with `pytest.fail(...)` need bodies.
   Pattern-matched stubs (InvalidURL, AliasTaken, LinkNotFound) may already pass.
   Flag-matrix tests use `FLAG_<NAME>=true|false` via monkeypatch until the app wires flags.

3. **Run the verification stack**:

   ```bash
   python3 .../engine/check_metadata.py --root .
   python3 .../engine/generate_verification.py --root . --check
   python3 .../engine/generate_flag_matrix.py --root . --check
   python3 .../engine/generate_gherkin.py --root . --check
   PYTHONPATH=src pytest -q
   ```

4. **Report** — list pass/fail per layer:
   - Tier-1 metadata gate
   - Contract stubs up to date (`--check`)
   - Flag-matrix stubs up to date
   - Gherkin features up to date
   - pytest green (skip flag-matrix failures until bodies implemented, but report them)

5. **Not done until gate + stub checks pass and pytest is green** on implemented tests.
   For long-running work, loop: implement → verify → commit.

## Long-running / goal sessions

Use **work packets** with a frozen done predicate (see `docs/verification-loop.md`):

```
repeat until DONE(packet):
  implement smallest slice
  run this skill (full stack)
  if fail → fix, do not advance to next packet
```

Brain MCP and LSP are for **orientation only** — never substitute for this stack.
End the session when every packet is green, not when the agent "feels" complete.

## Optional: semantic freshness

Before merge, run `/freshness-review` on the diff (Tier-2: does prose still match code?).

## Why this enables long runs

The missing piece isn't more autonomy — it's a **machine-checkable done predicate**.
pytest + gates are the oracle. Contracts are the spec; generated tests are the
executable slice. Meaning, definition, and verification stay on the same WAL.