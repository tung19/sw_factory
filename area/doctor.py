"""area.doctor — check a user's local setup for the local-first workflow.

Everything runs on the user's own machine (see docs/adr/0001), so this reports
what is present/missing: Python, Node, git, optional gh, a Claude LLM path
(keyless Claude Code or an API key), and optional deploy credentials.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

# Each check returns (name, status, detail, fix). status in {ok, warn, fail}.
Check = tuple[str, str, str, str]


def _which(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _ver(cmd: list[str]) -> str | None:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except Exception:  # noqa: BLE001
        return None
    if r.returncode != 0:
        return None
    out = (r.stdout or r.stderr).strip()
    return out.splitlines()[0] if out else None


def check_python() -> Check:
    v = sys.version_info
    ok = (v.major, v.minor) >= (3, 12)
    return ("Python ≥ 3.12", "ok" if ok else "fail", f"{v.major}.{v.minor}.{v.micro}",
            "" if ok else "cài Python 3.12+ (vd: uv python install 3.12)")


def check_node() -> Check:
    v = _ver(["node", "--version"])
    return ("Node.js", "ok" if v else "fail", v or "(không thấy)",
            "" if v else "cài Node 18+ (nodejs.org, hoặc nvm install 20)")


def check_git() -> Check:
    ok = _which("git")
    return ("git", "ok" if ok else "fail", _ver(["git", "--version"]) or "",
            "" if ok else "cài git")


def check_gh() -> Check:
    ok = _which("gh")
    return ("GitHub CLI (gh)", "ok" if ok else "warn", "" if not ok else "có",
            "" if ok else "tùy chọn — cần cho `area export --create/--push` (cli.github.com)")


def check_llm() -> Check:
    if os.getenv("ANTHROPIC_API_KEY"):
        return ("Claude (LLM)", "ok", "ANTHROPIC_API_KEY đã set", "")
    if _which("claude"):
        return ("Claude (LLM)", "ok", "Claude Code CLI có (keyless ACP)", "")
    return ("Claude (LLM)", "warn", "(không thấy)",
            "login Claude Code (keyless) HOẶC: export ANTHROPIC_API_KEY=…")


def check_deploy() -> Check:
    have = []
    if _which("cf") or os.getenv("CLOUDFLARE_API_TOKEN"):
        have.append("cloudflare")
    if os.getenv("VERCEL_TOKEN"):
        have.append("vercel")
    return ("Deploy creds (tùy chọn)", "ok" if have else "warn",
            ", ".join(have) or "(chưa có — chỉ cần khi deploy)",
            "" if have else "login khi cần: cf auth login / export VERCEL_TOKEN=…")


def check_workspace() -> Check:
    """Where generated apps land. The default puts them INSIDE this repo, and the
    build agent runs unsandboxed on the host — so by default an agent can reach
    AREA's own code. `tools/verify-factory-intact.sh` detects a change mid-run;
    pointing AREA_WORKSPACE outside the repo prevents one."""
    from area.paths import REPO, workspace

    ws = workspace()
    inside = ws == REPO or REPO in ws.parents
    if not inside:
        return ("workspace", "ok", f"{ws} (outside the factory repo)", "")
    return ("workspace", "warn",
            f"{ws} is INSIDE the factory repo — a build agent writing there can reach "
            "AREA's own code",
            "export AREA_WORKSPACE=~/area-generated  (the factory-intact check still "
            "detects a mid-run change either way)")


def report() -> list[Check]:
    return [check_python(), check_node(), check_git(), check_gh(), check_llm(),
            check_deploy(), check_workspace()]
