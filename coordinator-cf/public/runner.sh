#!/usr/bin/env bash
# AREA runner — ONE-COMMAND bootstrap (BYO: everything runs HERE on your machine
# with YOUR Claude + Cloudflare/Vercel; nothing but log lines leaves). Served by
# the coordinator at <coordinator>/runner.sh, so a user pairs in one line:
#
#   curl -fsSL https://area-coordinator.monbkel.workers.dev/runner.sh | bash -s -- --token <pairing-token>
#
# It clones AREA (first run), installs it (venv), and connects as a runner. Needs:
# git, Python 3.12+, and either a Claude Code login (keyless, default) or an LLM key
# (export AREA_RUNNER_BACKEND=llm LLM_API_KEY=… LLM_MODEL=…). Re-running updates +
# reconnects. Private repo ⇒ you need git/gh access to it.
set -euo pipefail

COORD="${AREA_COORD_URL:-wss://area-coordinator.monbkel.workers.dev}"
REPO="${AREA_REPO:-https://github.com/tung19/sw_factory.git}"
DIR="${AREA_HOME:-$HOME/.area-runner}"
TOK="${AREA_PAIR_TOKEN:-}"
while [ $# -gt 0 ]; do
  case "$1" in
    --token)   TOK="$2"; shift 2;;
    --connect) COORD="$2"; shift 2;;
    -h|--help) echo "usage: curl .../runner.sh | bash -s -- --token <token>"; exit 0;;
    *) shift;;
  esac
done

echo "▶ AREA runner bootstrap (chạy trên MÁY CỦA BẠN)"
command -v git >/dev/null 2>&1 || { echo "❌ cần git"; exit 1; }

if [ ! -d "$DIR/.git" ]; then
  echo "▶ Clone AREA → $DIR …"
  if ! git clone --depth 1 "$REPO" "$DIR" 2>/dev/null; then
    echo "❌ Clone thất bại. Repo private ⇒ cần quyền git/gh. Thử: gh auth login, rồi chạy lại." >&2
    exit 1
  fi
else
  echo "▶ Cập nhật AREA ($DIR) …"
  git -C "$DIR" pull --ff-only >/dev/null 2>&1 || true
fi

echo "▶ Cài + kết nối runner → $COORD"
exec bash "$DIR/scripts/run-runner.sh" --connect "$COORD" ${TOK:+--token "$TOK"}
