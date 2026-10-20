#!/usr/bin/env bash
# Deploy a built app to YOUR infra (wraps the deterministic area.deploy): auto-detects
# Cloudflare (vinext) vs Vercel, provisions D1/Postgres if the app persists, verifies
# provenance, then `wrangler`/`vercel` deploy with your own login. No agent.
#   tools/deploy.sh <app-name> [--require-provenance]
set -euo pipefail
cd "$(dirname "$0")/.."
APP="${1:?usage: deploy.sh <app-name> [--require-provenance]}"; shift || true
exec .venv/bin/area deploy "$APP" --yes "$@"
