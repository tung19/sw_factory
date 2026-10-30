#!/usr/bin/env bash
# Build a self-contained review package for a blind reviewer (P8), adapted from
# superpowers:subagent-driven-development/review-package. It emits the commit list, the
# diffstat, and a wide-context diff for BASE..HEAD — the ONE artifact a reviewer subagent
# reads, so the reviewer never crawls the working tree or sees the builder's chat.
#
# Two determinism guards (the reason this is a script, not a prompt):
#   * HEAD must be a descendant of BASE (no stale / unrelated range)  -> exit 3
#   * the range must be non-empty (something to review)               -> exit 3
#
#   tools/review-package.sh <base> <head> [outfile]   # to <outfile> if given, else stdout
set -euo pipefail

BASE="${1:?usage: review-package.sh <base> <head> [outfile]}"
HEAD="${2:?usage: review-package.sh <base> <head> [outfile]}"
OUT="${3:-}"

git rev-parse --verify --quiet "$BASE^{commit}" >/dev/null || {
  echo "review-package.sh: not a commit: $BASE" >&2; exit 2; }
git rev-parse --verify --quiet "$HEAD^{commit}" >/dev/null || {
  echo "review-package.sh: not a commit: $HEAD" >&2; exit 2; }

git merge-base --is-ancestor "$BASE" "$HEAD" || {
  echo "review-package.sh: HEAD ($HEAD) is not a descendant of BASE ($BASE) — stale range" >&2
  exit 3; }

if [ -z "$(git rev-list "$BASE..$HEAD")" ]; then
  echo "review-package.sh: empty range $BASE..$HEAD — nothing to review" >&2
  exit 3
fi

emit() {
  echo "# Review package: $BASE..$HEAD"
  echo
  echo "## Commits"
  git log --oneline "$BASE..$HEAD"
  echo
  echo "## Diffstat"
  git diff --stat "$BASE..$HEAD"
  echo
  echo "## Diff (-U10)"
  git diff -U10 "$BASE..$HEAD"
}

if [ -n "$OUT" ]; then emit > "$OUT"; echo "review-package.sh: wrote $OUT"; else emit; fi
