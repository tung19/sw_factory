#!/usr/bin/env bash
# Lock an app's holdout oracle (independence enforcement #b). Records a checksum of
# every file under __tests__/_holdout/ so later build steps can't silently tamper
# with the test oracle. Run this AFTER authoring the holdout, BEFORE implementing.
#   tools/lock-holdout.sh <app-name> [workspace-dir]
set -euo pipefail
APP="${1:?usage: lock-holdout.sh <app-name> [workspace-dir]}"
WS="${2:-workspace}"
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
