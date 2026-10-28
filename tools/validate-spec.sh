#!/usr/bin/env bash
# Validate a spec artifact against the SAME contract the factory enforces, BEFORE
# `area run --use-spec` (or clone/intake/iterate) builds from it. This is the seam a
# separate spec engine plugs into: emit specs/<name>/{spec.yaml,acceptance.yaml}, run
# this, build only on a green contract.
#
# It calls area.spec.models.{load_spec,load_acceptance,validate_cross,routes_unquoted}
# DIRECTLY — it does not re-implement the rules — so it can never drift from the gate
# the factory itself applies (area/spec/extract.py:_spec_verifier).
#
#   tools/validate-spec.sh <app-name | path-to-specs-dir> [workspace-dir] [--strict]
#
# Exit 0 = contract OK (advisory warnings may still print). Non-zero = a FATAL problem,
# or, under --strict, an advisory one too (a criterion that navigates without quoting a
# declared route — the holdout author sees ONLY acceptance.yaml, so an unnamed path gets
# invented and the frozen oracle asserts against a URL the app may not serve).
set -euo pipefail
. "$(dirname "$0")/_workspace.sh"

# Importing `area` pulls in the agent SDK, which prints a startup banner to stdout.
# This tool's stdout is meant to be clean (and parseable), so silence it.
export OPENHANDS_SUPPRESS_BANNER=1

TARGET="${1:-}"
[ -n "$TARGET" ] || { echo "usage: validate-spec.sh <app-name | specs-dir> [workspace-dir] [--strict]" >&2; exit 2; }
shift

STRICT=""
WS=""
for a in "$@"; do
  case "$a" in
    --strict) STRICT="--strict";;
    *) WS="$a";;
  esac
done

# $1 may be a specs dir straight from the spec engine, or an app name under the
# workspace. A directory that already holds spec.yaml wins; otherwise resolve by name.
if [ -d "$TARGET" ] && [ -f "$TARGET/spec.yaml" ]; then
  SPEC_DIR="$TARGET"
else
  WS="${WS:-$(area_workspace)}"
  SPEC_DIR="$WS/specs/$TARGET"
fi

[ -f "$SPEC_DIR/spec.yaml" ] || { echo "❌ không thấy spec.yaml ở $SPEC_DIR — spec engine phải ghi spec.yaml + acceptance.yaml vào đây trước." >&2; exit 2; }
[ -f "$SPEC_DIR/acceptance.yaml" ] || { echo "❌ không thấy acceptance.yaml ở $SPEC_DIR (spec.yaml có, acceptance.yaml thiếu)." >&2; exit 2; }

PY="$(area_python)" || { echo "validate-spec.sh: no python found (.venv/bin/python, python3, python)" >&2; exit 2; }

"$PY" - "$SPEC_DIR" "$STRICT" <<'PYEOF'
import sys
from pathlib import Path

from area.spec.models import (
    load_acceptance,
    load_spec,
    routes_unquoted,
    validate_cross,
)

d = Path(sys.argv[1])
strict = sys.argv[2] == "--strict"

try:
    spec = load_spec(d / "spec.yaml")
except Exception as e:                       # missing / invalid yaml / schema mismatch
    print(f"❌ spec.yaml invalid: {e}")
    sys.exit(1)
try:
    acc = load_acceptance(d / "acceptance.yaml")
except Exception as e:
    print(f"❌ acceptance.yaml invalid: {e}")
    sys.exit(1)

problems = validate_cross(spec, acc)         # the exact FATAL set the factory enforces
if problems:
    print(f"❌ spec KHÔNG hợp lệ — {len(problems)} lỗi contract:")
    for p in problems:
        print(f"   • {p}")
    sys.exit(1)

# Advisory (fatal only under --strict): criteria that navigate without quoting a
# declared route. Not in `problems` unless spec.routes is empty, but it is the #1
# contract gotcha for a spec engine, so surface it either way.
unquoted = routes_unquoted(spec, acc)
if unquoted:
    print(f"⚠ {len(unquoted)} tiêu chí điều hướng mà không nêu route literal: "
          f"{', '.join(unquoted)}")
    print("   Holdout author CHỈ thấy acceptance.yaml — path không viết literal trong "
          "given/when/then sẽ bị BỊA. Hãy quote path (\"when they request /boards/7\").")
    if strict:
        print("❌ --strict: coi cảnh báo self-containment là lỗi.")
        sys.exit(1)

print(f"✅ Contract OK — {len(spec.features)} features, {len(acc.criteria)} AC, "
      f"{len(spec.routes)} routes. Sẵn sàng `area run --use-spec`.")
PYEOF
