#!/usr/bin/env bash
# AREA — local-first installer. Everything runs on YOUR machine with YOUR
# accounts (see docs/adr/0001). Run from the repo root after `git clone`:
#     bash scripts/install.sh
set -euo pipefail
cd "$(dirname "$0")/.."   # repo root

echo "▶ AREA installer (local-first)"

# --- 1. Python 3.12+ ---------------------------------------------------------
PY=""
for c in python3.12 python3.13 python3; do
  if command -v "$c" >/dev/null 2>&1; then
    v="$("$c" -c 'import sys;print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
    if [ "$(printf '%s\n%s\n' "3.12" "$v" | sort -V | head -1)" = "3.12" ]; then PY="$c"; break; fi
  fi
done
if [ -z "$PY" ]; then
  echo "❌ Cần Python 3.12+ (vd: 'uv python install 3.12' hoặc python.org). Cài xong chạy lại."
  exit 1
fi
echo "  ✓ $("$PY" --version)"

# --- 2. venv + install area --------------------------------------------------
echo "▶ Tạo venv + cài area…"
"$PY" -m venv .venv
./.venv/bin/pip install -q --upgrade pip
./.venv/bin/pip install -q -e .
echo "  ✓ area đã cài (editable)"

# --- 3. môi trường -----------------------------------------------------------
echo "▶ Kiểm tra môi trường:"
./.venv/bin/area doctor || true

cat <<'EOF'

▶ Xong. Bước tiếp (tất cả dùng tài khoản của BẠN):
  1) Claude (LLM):  đăng nhập Claude Code (keyless)  —  hoặc  export ANTHROPIC_API_KEY=…
  2) Deploy (khi cần):  đăng nhập Cloudflare / Vercel của bạn
  3) Chạy dashboard:
        source .venv/bin/activate
        area gui                 # tự mở http://127.0.0.1:8787

Mọi thứ chạy trên MÁY BẠN, không gửi code hay credentials đi đâu. (docs/adr/0001)
EOF
