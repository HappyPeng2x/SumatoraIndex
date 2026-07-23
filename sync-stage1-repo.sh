#!/usr/bin/env bash
# Sync a stage-1 generated JSON directory into its own GitHub repo, preserving
# any hand-maintained files already committed there (LICENSE, README.md,
# .gitignore) -- only the generator-produced paths listed on the command line
# are replaced/pruned, so a fresh generator run can never delete attribution
# files it doesn't know about.
#
# Usage: sync-stage1-repo.sh <local-source-dir> <owner/repo> <generated-path> [<generated-path> ...]
#
# Requires GH_SYNC_TOKEN in the environment: a token with push access to
# <owner/repo> (see release-dictionaries.yml's DICT_REPOS_PAT secret).

set -euo pipefail

SRC=$1
REPO_SLUG=$2
shift 2
GENERATED_PATHS=("$@")

if [ -z "${GH_SYNC_TOKEN:-}" ]; then
  echo "GH_SYNC_TOKEN is not set" >&2
  exit 1
fi

WORKDIR=$(mktemp -d)
trap 'rm -rf "$WORKDIR"' EXIT

git clone --depth 1 "https://x-access-token:${GH_SYNC_TOKEN}@github.com/${REPO_SLUG}.git" "$WORKDIR/repo"
cd "$WORKDIR/repo"
git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"

for path in "${GENERATED_PATHS[@]}"; do
  rm -rf "./${path:?}"
  if [ -d "$SRC/$path" ]; then
    mkdir -p "$(dirname "./$path")"
    cp -r "$SRC/$path" "./$path"
  elif [ -f "$SRC/$path" ]; then
    mkdir -p "$(dirname "./$path")"
    cp "$SRC/$path" "./$path"
  fi
done

git add -A -- "${GENERATED_PATHS[@]}"

# Optional: capture an exact add/modify/delete diff against the previous
# release's snapshot (this clone's HEAD, since it's `--depth 1`) for
# build-changelog.py to consume. No-op when unset, so manual/local
# invocations behave exactly as before this was added.
if [ -n "${DIFF_OUT:-}" ]; then
  git diff --cached --name-status -- "${GENERATED_PATHS[@]}" > "$DIFF_OUT"
fi

if git diff --cached --quiet; then
  echo "  $REPO_SLUG: no changes"
else
  git commit -q -m "Sync from SumatoraIndex ($(date -u +%Y-%m-%d))"
  BRANCH=$(git symbolic-ref --short HEAD)
  git push origin "HEAD:$BRANCH"
  echo "  $REPO_SLUG: pushed to $BRANCH"
fi
