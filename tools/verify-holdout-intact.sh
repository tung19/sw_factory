#!/usr/bin/env bash
# Verify an app's holdout oracle hasn't changed since it was locked (independence
# enforcement #b). Exit 0 = intact; non-zero = tampered → revert the holdout to its
# locked version and fix the IMPLEMENTATION instead. Run before/after each build step.
#   tools/verify-holdout-intact.sh <app-name> [workspace-dir]
set -euo pipefail
APP="${1:?usage: verify-holdout-intact.sh <app-name> [workspace-dir]}"
# Default the workspace to the one AREA actually resolves (AREA_WORKSPACE-aware), not
# the literal `workspace/` next to this repo. Generated apps live OUTSIDE the repo by
# default, so the old `${2:-workspace}` made this command fail when run exactly as
# CLAUDE.md prescribes — and fail with "hãy viết test holdout trước", blaming the
# operator for a missing oracle while the real one sat in the real app directory. The
# Python callers always pass $2 explicitly, so they were unaffected; it was the
# documented MANUAL path that was broken.
_resolve_ws() {
  if [ -x .venv/bin/python ]; then
    .venv/bin/python -c 'from area.paths import WORKSPACE; print(WORKSPACE)' 2>/dev/null && return
  fi
  printf 'workspace\n'
}
WS="${2:-$(_resolve_ws)}"
HOLD="$WS/apps/$APP/__tests__/_holdout"
LOCK="$WS/specs/$APP/holdout.lock"

holdout_hashes() {
  local tool; if command -v sha256sum >/dev/null 2>&1; then tool="sha256sum"; else tool="shasum -a 256"; fi
  ( cd "$HOLD" && find . -type f ! -name '_CHALLENGE.md' | LC_ALL=C sort \
      | while IFS= read -r f; do $tool "$f"; done )
}

[ -f "$LOCK" ] || { echo "❌ chưa khoá holdout ($LOCK) — chạy tools/lock-holdout.sh trước." >&2; exit 2; }
if diff <(holdout_hashes) "$LOCK" >/dev/null 2>&1; then
  echo "✅ Holdout nguyên vẹn — oracle độc lập được giữ."
else
  echo "❌ HOLDOUT BỊ ĐỔI — oracle đã bị can thiệp. Khôi phục holdout về bản khoá rồi build lại:" >&2
  diff <(holdout_hashes) "$LOCK" | head -20 >&2
  exit 1
fi
