#!/usr/bin/env bash
# Deploy the AREA coordinator to YOUR Cloudflare Workers (Worker + Durable Object).
# Needs your Cloudflare auth: `npx wrangler login` (or export CLOUDFLARE_API_TOKEN=…).
# The coordinator only relays — no agents, no secrets (ADR 0002). The factory runs
# on each user's runner; see docs/RUNNER.md.
set -euo pipefail
cd "$(dirname "$0")/.."
# keep the Worker's served UI in sync with the canonical coordinator UI
cp area/net/static/index.html coordinator-cf/public/index.html
# the one-command runner bootstrap, served at <coordinator>/runner.sh
cp scripts/bootstrap-runner.sh coordinator-cf/public/runner.sh
export npm_config_cache="${npm_config_cache:-$HOME/.cache/npm-area}"; mkdir -p "$npm_config_cache"
cd coordinator-cf
echo "▶ Deploy coordinator → Cloudflare Workers"
npx --yes wrangler deploy
