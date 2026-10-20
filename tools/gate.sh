#!/usr/bin/env bash
# Deterministic verification gates for a built app — NO agent (Claude Code is the
# agent; these just measure/check). Security audit + NFR budget always; add --e2e to
# run existing Playwright specs. A blocking failure exits non-zero → do not deploy.
#   tools/gate.sh <app-name> [--e2e] [--strict]
set -euo pipefail
cd "$(dirname "$0")/.."
APP="${1:?usage: gate.sh <app-name> [--e2e] [--strict]}"; shift || true
AREA=".venv/bin/area"; PY=".venv/bin/python"
STRICT=""; E2E=""
for a in "$@"; do case "$a" in --strict) STRICT="--strict";; --e2e) E2E=1;; esac; done

echo "▶ Gate 1/3 — security audit (tsc + npm audit + secrets, 2-tier)"
"$AREA" audit "$APP" $STRICT        # deterministic (no --fix; Claude Code fixes, not an inner agent)

echo "▶ Gate 2/3 — NFR budget (bundle/deps/weight vs specs/<name>/nfr.yaml)"
"$PY" - "$APP" <<'PYEOF'
import sys
from area.verify.nfr import nfr_verify
sys.exit(0 if nfr_verify(sys.argv[1], strict=False) else 1)
PYEOF

if [ -n "$E2E" ]; then
  if [ -d "workspace/apps/$APP/e2e" ]; then
    echo "▶ Gate 3/3 — e2e (Playwright, the specs you authored)"
    ( cd "workspace/apps/$APP" && npx playwright test )
  else
    echo "⚠ --e2e nhưng chưa có e2e/ — hãy tự viết Playwright specs (1/AC) cho app có auth/form, rồi chạy lại."
  fi
fi
echo "✅ Gates passed."
