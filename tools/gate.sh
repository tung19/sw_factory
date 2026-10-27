#!/usr/bin/env bash
# Deterministic verification gates for a built app — NO agent (Claude Code is the
# agent; these just measure/check). A blocking failure exits non-zero → do not deploy.
#   tools/gate.sh <app-name> [--e2e] [--chaos] [--perf] [--strict]
#
# SCOPE: this covers 5 of the registry's 9 gates — audit, nfr, visual, and (opt-in)
# e2e, chaos, perf. `verify`/holdout runs inside the build loop, and `product` and
# `cost` are Python-only gates reached through `area run/clone --all`. Said out loud
# because CLAUDE.md step 3 points the builder HERE, and a gate command that quietly
# covers half the registry reads as full coverage.
#
# Three bugs this script had, both of which made it LIE about coverage:
#
#  * `--chaos` was not parsed at all. CLAUDE.md step 3 tells the builder to pass
#    `--e2e --chaos`, so every such invocation silently ran no chaos gate. Unknown
#    flags are now a hard error rather than a silent no-op — that is the root cause,
#    not the missing branch.
#  * the e2e gate looked in `workspace/apps/$APP`, a repo-relative path. Generated apps
#    live in AREA_WORKSPACE (`~/area-generated` by default), so it never found them and
#    printed "chưa có e2e/ — hãy tự viết Playwright specs": blaming the operator for
#    missing specs while 12 of them sat in the real app directory. `--e2e` is MANDATORY
#    for any app with auth/sessions/forms (CLAUDE.md step 3), so the one gate the rules
#    call non-optional was the one being skipped. The app directory is now resolved
#    through `area.paths`, the way the visual gate below already did it.
#  * `perf` was not run at all, though `docs/CASE-STUDY.md` tabled a perf result as part
#    of "the gates". It is opt-in (`--perf`) rather than default: it boots the app and
#    fires concurrent load, which is slow, and making it default would quietly change
#    what every existing invocation does.
set -euo pipefail
cd "$(dirname "$0")/.."
APP="${1:?usage: gate.sh <app-name> [--e2e] [--chaos] [--perf] [--strict]}"; shift || true
AREA=".venv/bin/area"; PY=".venv/bin/python"
STRICT=""; E2E=""; CHAOS=""; PERF=""
for a in "$@"; do
  case "$a" in
    --strict) STRICT="--strict";;
    --e2e) E2E=1;;
    --chaos) CHAOS=1;;
    --perf) PERF=1;;
    *) echo "gate.sh: unknown option '$a'" >&2
       echo "usage: gate.sh <app-name> [--e2e] [--chaos] [--perf] [--strict]" >&2; exit 2;;
  esac
done

# AREA_WORKSPACE-aware: generated apps normally live OUTSIDE the repo.
APPDIR="$("$PY" -c 'import sys
from area.paths import WORKSPACE
print(WORKSPACE / "apps" / sys.argv[1])' "$APP")"
[ -d "$APPDIR" ] || { echo "gate.sh: no app at $APPDIR" >&2; exit 2; }

TOTAL=3
for f in "$E2E" "$CHAOS" "$PERF"; do [ -n "$f" ] && TOTAL=$((TOTAL+1)); done
N=0; step() { N=$((N+1)); echo "▶ Gate $N/$TOTAL — $1"; }

step "security audit (tsc + npm audit + secrets, 2-tier)"
"$AREA" audit "$APP" $STRICT        # deterministic (no --fix; Claude Code fixes, not an inner agent)

step "NFR budget (bundle/deps/weight vs specs/<name>/nfr.yaml)"
"$PY" - "$APP" <<'PYEOF'
import sys
from area.verify.nfr import nfr_verify
sys.exit(0 if nfr_verify(sys.argv[1], strict=False) else 1)
PYEOF

# Visual parity (clones): ADVISORY here by design — it prints a score + artifact path
# and never blocks this shell path. The blocking path is the Python gate registry
# (`area run/clone --visual --strict`, or a committed specs/<name>/visual.yaml).
step "visual parity (clone look vs specs/<name>/_ui, advisory)"
"$PY" - "$APP" <<'PYEOF' || echo "⚠ visual gate errored — ignoring (advisory)"
import sys
from area.verify.visual import visual_verify
visual_verify(sys.argv[1], strict=False)   # advisory here: never blocks this path
sys.exit(0)
PYEOF

if [ -n "$E2E" ]; then
  if [ -d "$APPDIR/e2e" ]; then
    step "e2e (Playwright, the specs you authored)"
    ( cd "$APPDIR" && npx playwright test )
  else
    echo "✗ --e2e requested but $APPDIR/e2e does not exist." >&2
    echo "  Write one Playwright spec per AC (CLAUDE.md step 3 makes this MANDATORY" >&2
    echo "  for any app with auth / sessions / forms), then re-run." >&2
    exit 1
  fi
fi

if [ -n "$CHAOS" ]; then
  if compgen -G "$APPDIR/__tests__/_chaos/*" >/dev/null; then
    step "chaos (hostile inputs, concurrency, failure injection)"
    ( cd "$APPDIR" && npx vitest run __tests__/_chaos )
  else
    echo "✗ --chaos requested but $APPDIR/__tests__/_chaos/ is empty or missing." >&2
    echo "  Generate it with \`area chaos $APP\` (that path may use an agent), then re-run." >&2
    exit 1
  fi
fi
if [ -n "$PERF" ]; then
  step "perf (boots the app, fires concurrent load, measures p50/p95/p99)"
  "$PY" - "$APP" $STRICT <<'PYEOF'
import sys
from area.verify.perf import perf_verify
sys.exit(0 if perf_verify(sys.argv[1], strict="--strict" in sys.argv) else 1)
PYEOF
fi
echo "✅ Gates passed."
