"""area.skills — ship AREA's skill pack into an app dir so the ACP Claude Code
agent discovers + uses them.

The build agent runs with the app dir as its working directory, and Claude Code
loads **project** skills from `<cwd>/.claude/skills/<name>/SKILL.md`. Verified
live (2026-10-19): the ACP/Claude Code session exposes the `Skill` tool and a
project skill both auto-matches and invokes via `/name`. So we copy the repo's
`skills/` into `<app>/.claude/skills/` right before the build runs.
"""
from __future__ import annotations

import shutil
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


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
