#!/usr/bin/env bash
# SLSA-style provenance for a built app (wraps the deterministic area.provenance).
#   tools/provenance.sh <app-name>            # record {spec digest -> gates -> artifact sha}
#   tools/provenance.sh <app-name> --verify   # check the artifact wasn't modified since
set -euo pipefail
cd "$(dirname "$0")/.."
APP="${1:?usage: provenance.sh <app-name> [--verify]}"; shift || true
exec .venv/bin/area provenance "$APP" "$@"
