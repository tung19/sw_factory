#!/usr/bin/env bash
# Lint generated tests for FIXED sleeps (P11, from superpowers:systematic-debugging/
# condition-based-waiting). An unconditional wait in a test is the #1 source of flakiness and
# the thing a "bump the timeout to make it pass" symptom-patch reaches for. Point this at a
# generated app's test dir (e.g. <app>/e2e); it exits 1 if it finds one, which should be
# replaced by a condition-based wait (poll a predicate, with a timeout + a clear error).
#
#   tools/check-no-fixed-sleeps.sh <dir>
set -euo pipefail

DIR="${1:?usage: check-no-fixed-sleeps.sh <dir>}"
[ -d "$DIR" ] || { echo "check-no-fixed-sleeps.sh: no dir at $DIR" >&2; exit 2; }

# Two unambiguous test-sleep smells: Playwright's waitForTimeout(<ms>) and a bare time.sleep(.
# Literal -E (not -P) for portability and to avoid the NUL-byte / grep -P pitfalls noted in the
# chaos-tests memory.
if hits="$(grep -rnE 'waitForTimeout\(|time\.sleep\(' "$DIR" 2>/dev/null)"; then
  echo "check-no-fixed-sleeps.sh: fixed sleeps found — use a condition-based wait instead:" >&2
  printf '%s\n' "$hits" >&2
  exit 1
fi
echo "check-no-fixed-sleeps.sh: no fixed sleeps in $DIR ✓"
