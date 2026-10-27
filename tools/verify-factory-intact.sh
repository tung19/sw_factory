#!/usr/bin/env bash
# Verify AREA's OWN code hasn't changed while a run was in progress.
#
# The holdout lock protects the ORACLE from the builder; this protects the FACTORY.
# The reference architecture puts the factory's code and configuration in the trusted
# row — "they change only through review, never during a run" (The Secure Software
# Factory, p.6) — but the build agent runs unsandboxed on the host and, with the
# default workspace (REPO/workspace), writes INSIDE this repo. Nothing stopped it from
# editing a gate's own checker, a skill, or `area/` itself mid-build. Same remedy as
# the holdout: checksum what must not change, and fail loudly if it did.
#
#   tools/verify-factory-intact.sh snapshot <lockfile>   # before the run
#   tools/verify-factory-intact.sh verify   <lockfile>   # after the run
#
# Exit 0 = intact. 1 = CHANGED (the diff names the files). 2 = usage/missing lock.
set -euo pipefail
MODE="${1:?usage: verify-factory-intact.sh snapshot|verify <lockfile>}"
LOCK="${2:?usage: verify-factory-intact.sh snapshot|verify <lockfile>}"
cd "$(dirname "$0")/.."

# Only paths that exist — a clone may legitimately lack skills/ or .claude/settings.json.
TARGETS=()
for t in area tools skills .claude/settings.json; do
  [ -e "$t" ] && TARGETS+=("$t")
done
[ ${#TARGETS[@]} -gt 0 ] || { echo "❌ nothing to checksum (not an AREA checkout?)" >&2; exit 2; }

factory_hashes() {
  local tool
  if command -v sha256sum >/dev/null 2>&1; then tool="sha256sum"; else tool="shasum -a 256"; fi
  # Build artefacts are not source: a run legitimately writes .pyc files.
  find "${TARGETS[@]}" -type f \
       ! -name '*.pyc' ! -name '.DS_Store' ! -path '*/__pycache__/*' \
    | LC_ALL=C sort \
    | while IFS= read -r f; do $tool "$f"; done
}

case "$MODE" in
  snapshot)
    mkdir -p "$(dirname "$LOCK")"
    factory_hashes > "$LOCK"
    echo "✅ factory snapshot: $(wc -l < "$LOCK" | tr -d ' ') file(s) → $LOCK"
    ;;
  verify)
    [ -f "$LOCK" ] || { echo "❌ no factory snapshot at $LOCK — run 'snapshot' first." >&2; exit 2; }
    if diff <(factory_hashes) "$LOCK" >/dev/null 2>&1; then
      echo "✅ factory intact — AREA's own code/config unchanged during the run."
    else
      echo "❌ FACTORY CHANGED DURING THE RUN — the agent (or something else) edited" >&2
      echo "   AREA itself. The build cannot be trusted: a gate may have graded with" >&2
      echo "   modified code. Review these, revert, and rebuild:" >&2
      diff <(factory_hashes) "$LOCK" | head -20 >&2
      exit 1
    fi
    ;;
  *)
    echo "❌ unknown mode '$MODE' (snapshot|verify)" >&2; exit 2 ;;
esac
