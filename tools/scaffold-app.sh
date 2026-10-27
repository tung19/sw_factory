#!/usr/bin/env bash
# Scaffold a spec-driven workspace for an app (adapts the SDD "project workspace"
# layout). The app SOURCE stays at the ROOT where the framework expects it
# (package.json, app/, lib/ …); the SDD engineering docs / tasks / changelog sit
# alongside, and the LOCKED independent oracle lives under __tests__/_holdout/.
#   tools/scaffold-app.sh <app-name> [workspace-dir]
set -euo pipefail
cd "$(dirname "$0")/.."
APP="${1:?usage: scaffold-app.sh <app-name> [workspace-dir]}"
WS="${2:-workspace}"
ROOT="$WS/apps/$APP"
mkdir -p "$ROOT/docs" "$ROOT/tasks" "$ROOT/changelog" \
         "$ROOT/__tests__/_holdout" "$ROOT/tests/unit" "$ROOT/tests/integration" "$ROOT/tests/end-to-end"

doc() { # doc <file> <heading>  — write a thin stub only if missing
  [ -f "$ROOT/docs/$1" ] && return 0
  printf '# %s\n\n_(fill during the oracle-loop; keep thin — or skip — for a small app)_\n' "$2" > "$ROOT/docs/$1"
}
doc 01-engineering-intent.md        "01 · Engineering intent — why / goals (YOU define)"
doc 02-product-requirements.md      "02 · Product requirements + acceptance criteria (YOU define)"
doc 03-technical-spec.md            "03 · Technical spec — architecture, stack, key decisions"
doc 04-api-and-data-design.md       "04 · API & data design — routes, schema, data model"
doc 05-test-specification.md        "05 · Test specification — AC→test map, oracle strategy"
doc 06-security-and-reliability.md  "06 · Security & reliability — threats + audit results"
doc 07-deployment-and-monitoring.md "07 · Deployment & monitoring — target, live URL, monitors"
doc 08-maintenance-and-spec-drift.md "08 · Maintenance & spec drift — iterate log"

[ -f "$ROOT/tasks/agent-task-list.md" ] || echo "# Agent task list"$'\n' > "$ROOT/tasks/agent-task-list.md"
[ -f "$ROOT/tasks/review-notes.md" ]    || echo "# Review notes (Tung — human gate)"$'\n' > "$ROOT/tasks/review-notes.md"
[ -f "$ROOT/changelog/release-notes.md" ] || echo "# Release notes"$'\n' > "$ROOT/changelog/release-notes.md"

echo "✅ Scaffolded $ROOT"
echo "   SDD docs/ (01–08) + tasks/ + changelog/ + __tests__/_holdout/ (locked oracle) + tests/{unit,integration,end-to-end}."
echo "   App SOURCE goes at the ROOT ($ROOT) — package.json, app/, lib/, … where the framework expects it."
