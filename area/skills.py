"""area.skills — ship AREA's skill pack AND its holdout guardrail into an app dir,
so the ACP Claude Code agent both discovers the skills and *cannot* edit the oracle.

The build agent runs with the app dir as its working directory, and Claude Code
loads **project** skills from `<cwd>/.claude/skills/<name>/SKILL.md`. Verified
live (2026-10-19): the ACP/Claude Code session exposes the `Skill` tool and a
project skill both auto-matches and invokes via `/name`. So we copy the repo's
`skills/` into `<app>/.claude/skills/` right before the build runs.

Claude Code also loads **project hooks** from `<cwd>/.claude/settings.json`, and
until now nothing installed one — so the `PreToolUse` guard that makes a locked
holdout unwritable protected only an interactive session in the AREA repo, never
the autonomous agent that actually writes the app. For that agent, holdout
protection was detection-after-the-fact. `install_guardrail` closes that:
prevention now reaches the writer. See docs/harness2-gap-assessment.md F3.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"
HOOK_SRC = Path(__file__).resolve().parent.parent / "tools" / "hooks" / "guard_holdout.py"

# Fail-open if the script is missing, exactly as the repo's own settings.json does:
# a hook hiccup must never wedge a build. The guard derives the lock path from the
# EDITED FILE's realpath (workspace/apps/<name> -> workspace/specs/<name>), so it
# needs no knowledge of where it was installed.
_HOOK_CMD = (
    'f="$CLAUDE_PROJECT_DIR/.claude/hooks/guard_holdout.py"; '
    'if [ -f "$f" ]; then exec python3 -I "$f"; else exit 0; fi'
)
_HOOK_MATCHER = "Edit|Write|MultiEdit|NotebookEdit"


def skill_names(src: str | Path = SKILLS_DIR) -> list[str]:
    src = Path(src)
    if not src.is_dir():
        return []
    return sorted(p.name for p in src.iterdir() if (p / "SKILL.md").exists())


def install_skills(app_dir: str | Path, src: str | Path = SKILLS_DIR) -> list[str]:
    """Copy each skill from `src` into `<app_dir>/.claude/skills/`. Idempotent.
    Returns the installed skill names."""
    src = Path(src)
    dest = Path(app_dir) / ".claude" / "skills"
    names: list[str] = []
    if src.is_dir():
        dest.mkdir(parents=True, exist_ok=True)
        for p in src.iterdir():
            if not (p / "SKILL.md").exists():
                continue
            shutil.copytree(p, dest / p.name, dirs_exist_ok=True)
            names.append(p.name)
    return sorted(names)


def install_guardrail(app_dir: str | Path, src: str | Path = HOOK_SRC) -> bool:
    """Install the locked-holdout `PreToolUse` guard into `<app_dir>/.claude/`.

    Returns True when the app is guarded afterwards. Idempotent. Merges into an
    existing `settings.json` rather than replacing it, and refuses to clobber one
    it cannot parse — an unreadable settings file is the user's, not ours.
    """
    src = Path(src)
    if not src.is_file():
        return False
    claude = Path(app_dir) / ".claude"
    (claude / "hooks").mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, claude / "hooks" / "guard_holdout.py")

    f = claude / "settings.json"
    conf: dict[str, Any] = {}
    if f.exists():
        try:
            loaded = json.loads(f.read_text())
        except Exception:  # noqa: BLE001
            return False   # do not overwrite a file we did not understand
        if isinstance(loaded, dict):
            conf = loaded
    hooks = conf.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        return False
    pre = hooks.setdefault("PreToolUse", [])
    if not isinstance(pre, list):
        return False
    if not any(_is_our_hook(m) for m in pre):
        pre.append({"matcher": _HOOK_MATCHER,
                    "hooks": [{"type": "command", "command": _HOOK_CMD}]})
    f.write_text(json.dumps(conf, indent=2) + "\n")
    return True


def _is_our_hook(matcher: object) -> bool:
    if not isinstance(matcher, dict):
        return False
    return any(
        isinstance(h, dict) and "guard_holdout.py" in str(h.get("command", ""))
        for h in (matcher.get("hooks") or [])
    )


def skills_preamble(target: str = "") -> str:
    """A short nudge prepended to the build prompt. Auto-match already works, but
    naming the skills makes the headless/ACP path reliable (explicit `/name`)."""
    names = skill_names()
    if not names:
        return ""
    lines = ["You have AREA skills in this project (.claude/skills). Use them:"]
    if "area-oracle-loop" in names:
        lines.append("- /area-oracle-loop — the build discipline (lock the oracle, build to green, never self-judge).")
    if "vinext-cf-build" in names and (not target or target == "cloudflare"):
        lines.append("- /vinext-cf-build — Cloudflare (vinext) build + audit gotchas & fixes.")
    extra = [n for n in names if n not in ("area-oracle-loop", "vinext-cf-build")]
    for n in extra:
        lines.append(f"- /{n}")
    return "\n".join(lines) + "\n\n"
