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


def skill_targets(skill_dir: str | Path) -> tuple[str, ...]:
    """The build targets a skill applies to, from its SKILL.md frontmatter.

    Empty tuple = universal (applies to every target). A skill that names targets
    is DOMAIN knowledge: `vinext-cf-build` is Cloudflare-specific, and shipping it
    into a `plain` app put ~105 lines of irrelevant instruction in the builder's
    context while making every kind's version move whenever it was edited.
    Unparseable or absent frontmatter reads as universal — the safe direction,
    since a skill nobody scoped should keep reaching everyone.
    """
    f = Path(skill_dir) / "SKILL.md"
    try:
        text = f.read_text(errors="ignore")
    except OSError:
        return ()
    if not text.startswith("---"):
        return ()
    end = text.find("\n---", 3)
    if end == -1:
        return ()
    try:
        import yaml

        meta = yaml.safe_load(text[3:end]) or {}
    except Exception:  # noqa: BLE001
        return ()
    if not isinstance(meta, dict):
        return ()
    raw = meta.get("targets")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return ()
    return tuple(sorted(str(t).strip() for t in raw if str(t).strip()))


def applies_to(skill_dir: str | Path, target: str = "") -> bool:
    """Whether this skill reaches a build for `target`. No target given = install
    everything, which keeps every existing caller's behaviour."""
    scope = skill_targets(skill_dir)
    return not scope or not target or target in scope


def install_skills(app_dir: str | Path, src: str | Path = SKILLS_DIR,
                   target: str = "") -> list[str]:
    """Copy the skills that apply to `target` from `src` into
    `<app_dir>/.claude/skills/`. Idempotent. Returns the installed skill names.

    Scoping by target is what makes "a Cloudflare skill cannot affect a plain
    build" TRUE rather than assumed: `skills_preamble` already declined to NAME
    the CF skill for a plain build, but the files were copied in anyway, so a
    Claude Code session in that directory could still discover them.
    See docs/harness2-gap-assessment.md F2.
    """
    src = Path(src)
    dest = Path(app_dir) / ".claude" / "skills"
    names: list[str] = []
    if src.is_dir():
        dest.mkdir(parents=True, exist_ok=True)
        for p in src.iterdir():
            if not (p / "SKILL.md").exists() or not applies_to(p, target):
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
    # One rule for "does this skill reach this build", shared with install_skills —
    # the CF gate used to be hardcoded here while the installer copied everything,
    # so the prompt and the directory disagreed.
    names = [n for n in skill_names(SKILLS_DIR) if applies_to(SKILLS_DIR / n, target)]
    if not names:
        return ""
    lines = ["You have AREA skills in this project (.claude/skills). Use them:"]
    if "area-oracle-loop" in names:
        lines.append("- /area-oracle-loop — the build discipline (lock the oracle, build to green, never self-judge).")
    if "vinext-cf-build" in names:
        lines.append("- /vinext-cf-build — Cloudflare (vinext) build + audit gotchas & fixes.")
    extra = [n for n in names if n not in ("area-oracle-loop", "vinext-cf-build")]
    for n in extra:
        lines.append(f"- /{n}")
    return "\n".join(lines) + "\n\n"
