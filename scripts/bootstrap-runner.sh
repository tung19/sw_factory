#!/usr/bin/env bash
# AREA runner — ONE-COMMAND bootstrap (BYO: everything runs HERE on your machine
# with YOUR Claude + Cloudflare/Vercel; nothing but log lines leaves). Served by
# the coordinator at <coordinator>/runner.sh. Two modes:
#
#   # foreground (dies when the terminal closes):
#   curl -fsSL <coord>/runner.sh | bash -s -- --token <token>
#
#   # install as an ALWAYS-ON background service (auto-starts on login, the
#   # "install once, then just open the web + drop a doc" experience):
#   curl -fsSL <coord>/runner.sh | AREA_INSTALL_SERVICE=1 bash -s -- --token <token>
#
# It clones AREA (first run), installs it (venv), then runs/installs the runner.
# Needs: git, Python 3.12+, and a Claude Code login (keyless) or an LLM key.
set -euo pipefail

COORD="${AREA_COORD_URL:-wss://area-coordinator.monbkel.workers.dev}"
REPO="${AREA_REPO:-https://github.com/tung19/sw_factory.git}"
DIR="${AREA_HOME:-$HOME/.area-runner}"
TOK="${AREA_PAIR_TOKEN:-}"
SERVICE="${AREA_INSTALL_SERVICE:-}"
while [ $# -gt 0 ]; do
  case "$1" in
    --token)   TOK="$2"; shift 2;;
    --connect) COORD="$2"; shift 2;;
    --service) SERVICE=1; shift;;
    -h|--help) echo "usage: curl .../runner.sh | bash -s -- --token <token> [--service]"; exit 0;;
    *) shift;;
  esac
done

echo "▶ AREA runner bootstrap (chạy trên MÁY CỦA BẠN)"
command -v git >/dev/null 2>&1 || { echo "❌ cần git"; exit 1; }

if [ ! -d "$DIR/.git" ]; then
  echo "▶ Clone AREA → $DIR …"
  git clone --depth 1 "$REPO" "$DIR" 2>/dev/null \
    || { echo "❌ Clone thất bại. Repo private ⇒ cần quyền git/gh (gh auth login)." >&2; exit 1; }
else
  echo "▶ Cập nhật AREA ($DIR) …"
  git -C "$DIR" pull --ff-only >/dev/null 2>&1 || true
fi

[ -x "$DIR/.venv/bin/area" ] || { echo "▶ Cài area…"; bash "$DIR/scripts/install.sh"; }
AREABIN="$DIR/.venv/bin/area"

install_service() {
  local OS; OS="$(uname -s)"
  if [ "$OS" = "Darwin" ]; then
    local PLIST="$HOME/Library/LaunchAgents/dev.area.runner.plist"
    mkdir -p "$HOME/Library/LaunchAgents"
    cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>dev.area.runner</string>
  <key>ProgramArguments</key><array>
    <string>$AREABIN</string><string>runner</string>
    <string>--connect</string><string>$COORD</string>
    <string>--token</string><string>$TOK</string>
  </array>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$DIR/runner.log</string>
  <key>StandardErrorPath</key><string>$DIR/runner.log</string>
</dict></plist>
PL
    launchctl unload "$PLIST" 2>/dev/null || true
    launchctl load "$PLIST"
    echo "✅ Đã cài trợ lý AREA (dịch vụ nền). Tự chạy + tự khởi động khi bật máy."
    echo "   Log: $DIR/runner.log"
    echo "   Gỡ: launchctl unload \"$PLIST\" && rm \"$PLIST\""
  elif [ "$OS" = "Linux" ]; then
    local U="$HOME/.config/systemd/user"; mkdir -p "$U"
    cat > "$U/area-runner.service" <<SV
[Unit]
Description=AREA runner
After=network-online.target
[Service]
ExecStart=$AREABIN runner --connect $COORD --token $TOK
Restart=always
RestartSec=3
[Install]
WantedBy=default.target
SV
    systemctl --user daemon-reload 2>/dev/null || true
    systemctl --user enable --now area-runner.service 2>/dev/null \
      && echo "✅ Đã cài (systemd user service)." \
      || echo "⚠ systemd --user không khả dụng — chạy nền thủ công: nohup $AREABIN runner --connect $COORD --token $TOK &"
  else
    echo "⚠ OS chưa hỗ trợ service — chạy: $AREABIN runner --connect $COORD --token $TOK"
  fi
}

if [ -n "$SERVICE" ]; then
  install_service
else
  echo "▶ Kết nối runner (foreground) → $COORD   (Ctrl-C để dừng)"
  exec "$AREABIN" runner --connect "$COORD" ${TOK:+--token "$TOK"}
fi
