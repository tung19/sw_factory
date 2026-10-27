#!/usr/bin/env bash
# Deploy a built app to YOUR infra (wraps the deterministic area.deploy): auto-detects
# Cloudflare (vinext) vs Vercel, provisions D1/Postgres if the app persists, verifies
# provenance, then `wrangler`/`vercel` deploy with your own login. No agent.
# This wrapper used to force --yes, which silently bypassed the ONE human gate before
# production. It no longer does: you get the prompt (which now names the provider and
# any PRODUCTION database it will create/migrate). Pass --yes yourself to skip it.
#   tools/deploy.sh <app-name> [--yes] [--no-require-provenance] [--allow-provision-failure]
set -euo pipefail
cd "$(dirname "$0")/.."
APP="${1:?usage: deploy.sh <app-name> [--yes] [...]}"; shift || true
exec .venv/bin/area deploy "$APP" "$@"
