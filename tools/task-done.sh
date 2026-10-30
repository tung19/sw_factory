#!/usr/bin/env bash
# Record a build milestone to a per-app progress ledger — ONLY if its verify command
# passes. A compaction-proof resume record (adapted from superpowers:executing-plans/
# task-done): a build interrupted by a context reset reads the ledger and SKIPS milestones
# already proven green, instead of re-doing them. The line is appended by THIS script after
# the command exits 0, so a model cannot mark a milestone "done" by writing prose — that
# separation (a script, not a sentence, records the green) is the point.
#
#   tools/task-done.sh <app> <milestone> -- <verify-cmd...>   # run cmd; append iff exit 0
#   tools/task-done.sh <app> --show                           # print the ledger (or nothing)
#
# Ledger: <workspace>/apps/<app>/.area/progress.md (gitignored with the generated app).
set -euo pipefail

DIR="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
# shellcheck source=/dev/null
. "$DIR/_workspace.sh"

APP="${1:?usage: task-done.sh <app> <milestone> -- <cmd...>   |   task-done.sh <app> --show}"
shift
APPDIR="$(area_workspace)/apps/$APP"
LEDGER="$APPDIR/.area/progress.md"

if [ "${1:-}" = "--show" ]; then
  [ -f "$LEDGER" ] && cat "$LEDGER" || true
  exit 0
fi

MILESTONE="${1:?milestone name required (e.g. holdout-locked, build-green, gate-audit)}"
shift
[ "${1:-}" = "--" ] || { echo "task-done.sh: expected -- before the verify command" >&2; exit 2; }
shift
[ "$#" -ge 1 ] || { echo "task-done.sh: a verify command is required after --" >&2; exit 2; }
[ -d "$APPDIR" ] || { echo "task-done.sh: no app at $APPDIR" >&2; exit 2; }

# Run the verify command, capturing output; record ONLY on a clean exit.
set +e
OUT="$("$@" 2>&1)"; RC=$?
set -e
LAST="$(printf '%s\n' "$OUT" | tail -1)"

if [ "$RC" -ne 0 ]; then
  printf '%s\n' "$OUT" | tail -5 >&2
  echo "task-done.sh: '$*' exited $RC — milestone '$MILESTONE' NOT recorded" >&2
  exit "$RC"
fi

mkdir -p "$APPDIR/.area"
printf '%s\t%s\t(%s → %s)\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$MILESTONE" "$*" "$LAST" >> "$LEDGER"
echo "task-done.sh: recorded '$MILESTONE' ✓"
