#!/usr/bin/env bash
# Materialize a target repo's brain into its GitHub wiki.
# Usage: publish_wiki.sh <owner/repo> <token> <root> [src] [flags]
#   <root> is the consumer checkout (e.g. $GITHUB_WORKSPACE).
# Prereq: the wiki must already exist (create one page in the UI once).
set -euo pipefail

SLUG="${1:?usage: publish_wiki.sh <owner/repo> <token> <root> [src] [flags]}"
TOKEN="${2:-}"
ROOT="${3:?root (consumer checkout) required}"
SRC="${4:-}"
FLAGS="${5:-}"
ENGINE="$(cd "$(dirname "$0")" && pwd)"

URL="https://github.com/${SLUG}.wiki.git"
[ -n "$TOKEN" ] && URL="https://x-access-token:${TOKEN}@github.com/${SLUG}.wiki.git"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
if ! git clone --quiet "$URL" "$WORK"; then
  echo "ERROR: could not clone ${SLUG}.wiki.git. Initialize the wiki (create one page in the UI) first."
  exit 1
fi

ARGS=(--root "$ROOT" --brain "$WORK")
[ -n "$SRC" ] && ARGS+=(--src "$ROOT/$SRC")
[ -n "$FLAGS" ] && ARGS+=(--flags "$ROOT/$FLAGS")
python3 "$ENGINE/materialize.py" "${ARGS[@]}"

cd "$WORK"
git add -A
if git diff --cached --quiet; then
  echo "Wiki already up to date."
  exit 0
fi
git -c user.name="materializer-bot" -c user.email="materializer-bot@users.noreply.github.com" \
    commit -q -m "Materialize wiki from ${GITHUB_SHA:-local}"
git push --quiet
echo "Wiki updated → https://github.com/${SLUG}/wiki"
