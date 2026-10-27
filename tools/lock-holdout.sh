#!/usr/bin/env bash
# Lock an app's holdout oracle (independence enforcement #b). Records a checksum of
# every file under __tests__/_holdout/ so later build steps can't silently tamper
# with the test oracle. Run this AFTER authoring the holdout, BEFORE implementing.
#   tools/lock-holdout.sh <app-name> [workspace-dir]
set -euo pipefail
APP="${1:?usage: lock-holdout.sh <app-name> [workspace-dir]}"
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

[ -d "$HOLD" ] || { echo "❌ không thấy holdout: $HOLD — hãy viết test holdout (từ spec) trước." >&2; exit 1; }
mkdir -p "$(dirname "$LOCK")"
holdout_hashes > "$LOCK"
echo "✅ Đã khoá holdout: $(wc -l <"$LOCK" | tr -d ' ') file → $LOCK"
echo "   TỪ GIỜ KHÔNG được sửa holdout. Cần sửa → viết _CHALLENGE.md + hỏi Tung."
