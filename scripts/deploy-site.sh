#!/usr/bin/env bash
# Deploy the landing page (site/) to YOUR Cloudflare Pages.
# Needs your Cloudflare auth first:  npx wrangler login   (or export CLOUDFLARE_API_TOKEN=…)
# This is the ONLY thing the owner hosts — a static page. The factory itself
# runs on each user's machine (see docs/adr/0001).
set -euo pipefail
cd "$(dirname "$0")/.."
PROJECT="${1:-area-site}"
echo "▶ Deploy site/ → Cloudflare Pages (project: $PROJECT)"
npx --yes wrangler pages deploy site --project-name "$PROJECT"
