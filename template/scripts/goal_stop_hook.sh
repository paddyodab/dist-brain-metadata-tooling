#!/usr/bin/env bash
# Deterministic /goal oracle for distributed-brain repos — a Claude Code Stop hook.
#
# Claude Code's /goal evaluator is transcript-only (a small model reading what was
# surfaced); it can be talked into a false "done". This hook makes the done predicate
# UNFAKEABLE: it actually runs the verification stack and decides from the real exit code.
#
# Stop-hook contract:  exit 2 = keep working (reason on stderr) · exit 0 = condition met.
# Active ONLY when DIST_BRAIN_GOAL=1, so it is a no-op in normal sessions even though it
# fires after every turn. Enable a goal run by launching with the var set:
#   DIST_BRAIN_GOAL=1 claude        # then: /goal <condition>
#
# Env knobs:
#   DIST_BRAIN_GOAL=1                 activate (required)
#   DIST_BRAIN_GOAL_PREDICATE=...     done command (default: scripts/brain verify).
#       Legacy/boy-scout example:
#       "scripts/brain gate --since $BASE && scripts/brain generate --check && pytest -q"
#   DIST_BRAIN_REFRESH=1             on green, scripts/brain refresh for next-turn freshness (default on)
#   DIST_BRAIN_GOAL_MAX_TURNS=50     runaway guard so an impossible goal can't loop forever
set -uo pipefail

[ "${DIST_BRAIN_GOAL:-0}" = "1" ] || exit 0            # not a goal run → allow stop

REPO_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
cd "$REPO_DIR" 2>/dev/null || exit 0

# --- runaway guard: cap turns (counter keyed by repo path) -----------------------
MAX="${DIST_BRAIN_GOAL_MAX_TURNS:-50}"
key=$(printf '%s' "$REPO_DIR" | shasum 2>/dev/null | cut -c1-12 || echo brain)
COUNT_FILE="${TMPDIR:-/tmp}/dist-brain-goal-$key"
n=$(( $(cat "$COUNT_FILE" 2>/dev/null || echo 0) + 1 ))
if [ "$n" -gt "$MAX" ]; then
  echo "[dist-brain goal] turn cap $MAX reached — stopping. Delete $COUNT_FILE or raise DIST_BRAIN_GOAL_MAX_TURNS to keep going." >&2
  rm -f "$COUNT_FILE"
  exit 0
fi
printf '%s' "$n" > "$COUNT_FILE"

# --- the done predicate ----------------------------------------------------------
PREDICATE="${DIST_BRAIN_GOAL_PREDICATE:-scripts/brain verify}"
out="$(bash -c "$PREDICATE" 2>&1)"; rc=$?

if [ "$rc" -ne 0 ]; then
  echo "[dist-brain goal] NOT done (turn $n/$MAX) — verification stack is RED. Fix and continue:" >&2
  echo "$out" | tail -25 >&2
  exit 2                                                # block stop → Claude keeps working
fi

# --- green: refresh the brain for the next turn, clear counter, allow stop -------
if [ "${DIST_BRAIN_REFRESH:-1}" = "1" ]; then
  scripts/brain refresh >/dev/null 2>&1 || true
fi
rm -f "$COUNT_FILE"
echo "[dist-brain goal] verification stack GREEN — done predicate satisfied." >&2
exit 0
