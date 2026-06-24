# The `/goal` oracle — a deterministic Stop hook

**Status:** canonical · **Last updated:** 2026-06-24

How to make a long `/goal` run finish *correctly*, not just *eventually*.

## The problem it solves

Claude Code's `/goal` keeps working across turns until a **completion condition** holds —
but the evaluator is **transcript-only** (a small fast model reading what Claude surfaced;
it doesn't run commands). So "done" can be *claimed* into existence: the agent says the
tests pass, the evaluator believes the transcript, the goal clears on a lie.

The distributed brain already has the fix — a machine-checkable done predicate
(`check_metadata` + `generate --check` + `pytest`, see [`verification-loop.md`](verification-loop.md)).
This hook wires that predicate in as the **oracle**: a Stop hook that actually *runs* the
stack and decides from the real exit code. `/goal` is the **executor**; this is the **oracle**.

## How it works

`scripts/goal_stop_hook.sh` is a Claude Code **Stop hook** — it fires after every turn:

- **exit 2** → block the stop, feed the failing layer back to Claude as "keep working".
- **exit 0** → allow the stop; the condition is met.

It is a **no-op unless `DIST_BRAIN_GOAL=1`**, so it never touches normal sessions even
though it's always installed. On green it optionally runs `scripts/brain refresh` so the
next turn orients against the work it just wrote. A turn cap (`DIST_BRAIN_GOAL_MAX_TURNS`,
default 50) keeps an impossible goal from looping forever.

## Wiring (one time)

1. `init.sh` installs `scripts/goal_stop_hook.sh` and `.claude/settings.goal-hook.json`.
2. Merge the Stop hook from `settings.goal-hook.json` into your `.claude/settings.json`.

## Running a goal

```bash
DIST_BRAIN_GOAL=1 claude          # activates the hook for this session only
```
then, in the session:
```
/goal backfill+verify contracts across app/services until the stack is green; stop after 30 turns
```

Each turn: Claude works → the hook runs the predicate → **red** keeps it going (the failing
layer is shown) → **green** ends the goal.

### Greenfield vs legacy predicate

- **Default** (`scripts/brain verify`): full gate + generators `--check` + tests. Right for
  greenfield and mature repos.
- **Legacy / boy-scout**: a sparse repo fails the full gate on existing debt, so scope the
  predicate to the diff:
  ```bash
  DIST_BRAIN_GOAL=1 \
  DIST_BRAIN_GOAL_PREDICATE="scripts/brain gate --since main && scripts/brain generate --check && pytest -q --no-cov" \
  claude
  ```

## Env reference

| Var | Default | Meaning |
|-----|---------|---------|
| `DIST_BRAIN_GOAL` | `0` | `1` activates the hook (required for a goal run) |
| `DIST_BRAIN_GOAL_PREDICATE` | `scripts/brain verify` | the done command; non-zero exit = keep working |
| `DIST_BRAIN_REFRESH` | `1` | on green, run `scripts/brain refresh` for next-turn brain freshness |
| `DIST_BRAIN_GOAL_MAX_TURNS` | `50` | runaway guard |

## Notes

- **Grok `/goal`** has a tool-using verifier already — point its verification pass at the
  same `scripts/brain verify` instead of generic checks; same oracle, different harness.
- The counter lives at `$TMPDIR/dist-brain-goal-<repohash>`; delete it (or it self-clears on
  green / at the cap) if a previous interrupted run left it stale.
