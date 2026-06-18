#!/usr/bin/env bash
# Install the authoring kit (/feature command, CONTRIBUTING, PR template) into a
# consumer repo. Usage: ./init.sh <target-repo-dir>
set -euo pipefail

TARGET="${1:?usage: init.sh <target-repo-dir>}"
HERE="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$TARGET/.claude/commands" "$TARGET/.github"
cp "$HERE/template/feature.md"               "$TARGET/.claude/commands/feature.md"
cp "$HERE/template/CONTRIBUTING.md"          "$TARGET/CONTRIBUTING.md"
cp "$HERE/template/pull_request_template.md" "$TARGET/.github/pull_request_template.md"

echo "Installed authoring kit into $TARGET:"
echo "  .claude/commands/feature.md   (/feature)"
echo "  CONTRIBUTING.md               (metadata Definition of Done)"
echo "  .github/pull_request_template.md"
echo
echo "Next: add CI workflows that call the reusable workflows — see this repo's README."
