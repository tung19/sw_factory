#!/usr/bin/env bash
# Start an AREA runner on YOUR infra. It dials OUT to a coordinator and executes
# jobs here, using YOUR Claude + Cloudflare/Vercel. Nothing leaves this machine
# except log lines. See docs/RUNNER.md.
#
# Usage:
#   scripts/run-runner.sh --connect wss://coord.example.com --token <pairing-token>
#   AREA_COORD_URL=wss://… AREA_PAIR_TOKEN=… scripts/run-runner.sh
set -euo pipefail
cd "$(dirname "$0")/.."

URL="${AREA_COORD_URL:-}"; TOK="${AREA_PAIR_TOKEN:-}"
while [ $# -gt 0 ]; do
  case "$1" in
    --connect) URL="$2"; shift 2;;
    --token)   TOK="$2"; shift 2;;
    -h|--help) echo "usage: $0 --connect <coordinator-url> [--token <pairing-token>]"; exit 0;;
    *) echo "unknown arg: $1" >&2; exit 1;;
  esac
done

if [ -z "$URL" ]; then
  echo "❌ Cần --connect <coordinator-url> (ws://… hoặc wss://…), hoặc đặt AREA_COORD_URL." >&2
  exit 1
fi

# Install area on first run.
if [ ! -x .venv/bin/area ]; then
  echo "▶ Chưa cài area — chạy installer…"
  bash scripts/install.sh
fi

echo "▶ Kiểm môi trường:"
./.venv/bin/area doctor || true

echo "▶ Khởi động runner → $URL"
echo "   (dùng Claude + Cloudflare/Vercel CỦA BẠN; Ctrl-C để dừng)"
exec ./.venv/bin/area runner --connect "$URL" ${TOK:+--token "$TOK"}
