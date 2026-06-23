#!/usr/bin/env bash
# Install the authoring kit into a consumer repo.
#
# Usage:
#   ./init.sh <target-repo-dir> [wiki-owner/repo]
#
# Installs Claude commands (legacy) and Grok skills (preferred).
# With wiki-owner/repo, also drops a .grok/config.toml pointing at that repo's brain.
set -euo pipefail

TARGET="${1:?usage: init.sh <target-repo-dir> [owner/repo]}"
WIKI_REPO="${2:-}"
HERE="$(cd "$(dirname "$0")" && pwd)"
VENV_PY="$HERE/.venv/bin/python3"
MCP_SERVER="$HERE/mcp/server.py"

# ---- Claude (legacy) ----------------------------------------------------------
mkdir -p "$TARGET/.claude/commands" "$TARGET/.github"
cp "$HERE/template/feature.md"               "$TARGET/.claude/commands/feature.md"
cp "$HERE/template/infra.md"                  "$TARGET/.claude/commands/infra.md"
cp "$HERE/template/learning.md"              "$TARGET/.claude/commands/learning.md"
cp "$HERE/template/CONTRIBUTING.md"          "$TARGET/CONTRIBUTING.md"
cp "$HERE/template/pull_request_template.md" "$TARGET/.github/pull_request_template.md"

# ---- Grok skills --------------------------------------------------------------
for skill in feature infra learning freshness-review dist-brain verification orchestrator-handoff brain-ops; do
  mkdir -p "$TARGET/.grok/skills/$skill"
  cp "$HERE/template/grok/skills/$skill/SKILL.md" "$TARGET/.grok/skills/$skill/SKILL.md"
done

mkdir -p "$TARGET/scripts"
cp "$HERE/template/scripts/brain" "$TARGET/scripts/brain"
chmod +x "$TARGET/scripts/brain"
cp "$HERE/template/brain.conf.example" "$TARGET/brain.conf.example"

# ---- Grok MCP config (optional) -----------------------------------------------
if [[ -n "$WIKI_REPO" ]]; then
  OWNER="${WIKI_REPO%%/*}"
  REPO="${WIKI_REPO##*/}"
  mkdir -p "$TARGET/.grok"
  if [[ -x "$VENV_PY" ]]; then
    PY="$VENV_PY"
  else
    PY="$(command -v python3)"
  fi
  sed -e "s|DIST_BRAIN_TOOLING_VENV_PYTHON|$PY|g" \
      -e "s|DIST_BRAIN_TOOLING_MCP_SERVER|$MCP_SERVER|g" \
      -e "s|OWNER|$OWNER|g" \
      -e "s|REPO|$REPO|g" \
      "$HERE/template/grok/config.toml.tmpl" > "$TARGET/.grok/config.toml"
fi

echo "Installed authoring kit into $TARGET:"
echo "  Grok skills:"
echo "    .grok/skills/feature/          (/feature — contract-first capture)"
echo "    .grok/skills/infra/            (/infra — IaC tags + intent)"
echo "    .grok/skills/learning/         (/learning — route-by-half-life)"
echo "    .grok/skills/freshness-review/ (/freshness-review — Tier-2 semantic gate)"
echo "    .grok/skills/dist-brain/       (/dist-brain — query MCP brain)"
echo "    .grok/skills/verification/     (/verification — contract → pytest loop)"
echo "    .grok/skills/orchestrator-handoff/ (/orchestrator-handoff — plan → packet → delegate)"
echo "    .grok/skills/brain-ops/           (/brain-ops — scripts/brain CLI)"
echo "  Scripts:"
echo "    scripts/brain                     (materialize, infer, gate, generate, verify)"
echo "    brain.conf.example                (copy → brain.conf for BRAIN_SRC / paths)"
echo "  Claude commands (legacy):"
echo "    .claude/commands/feature.md"
echo "    .claude/commands/infra.md"
echo "    .claude/commands/learning.md"
echo "  Shared:"
echo "    CONTRIBUTING.md"
echo "    .github/pull_request_template.md"
if [[ -n "$WIKI_REPO" ]]; then
  echo "  MCP:"
  echo "    .grok/config.toml  (dist-brain → wiki/$WIKI_REPO/graph.json)"
  echo
  echo "Ensure dist-brain-metadata-tooling has a venv:"
  echo "  cd $HERE && python3 -m venv .venv && .venv/bin/pip install -r mcp/requirements.txt"
else
  echo
  echo "Tip: pass owner/repo to also install .grok/config.toml:"
  echo "  $0 $TARGET <owner>/<repo-with-wiki>"
fi
echo
echo "Next: add CI workflows — see README."