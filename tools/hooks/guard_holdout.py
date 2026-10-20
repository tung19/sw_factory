#!/usr/bin/env python3
"""AREA PreToolUse guard — refuse edits to a LOCKED holdout oracle.

This is the HARD layer of the oracle-loop's independence enforcement at the
Claude-Code editor level: CLAUDE.md *asks* the agent not to touch a locked
holdout; this hook *blocks* it. It turns "please don't" into "cannot".

Wired from .claude/settings.json as a PreToolUse hook on Edit|Write|MultiEdit|
NotebookEdit. It reads the tool call from stdin (JSON) and:
  - allows anything that is NOT inside a `__tests__/_holdout/` directory;
  - allows `_CHALLENGE.md` (the sanctioned escape hatch — excluded from the lock);
  - allows edits BEFORE the holdout is locked (the authoring phase);
  - BLOCKS (exit 2) an edit to a holdout whose `holdout.lock` already exists,
    pointing the agent at the implementation / the _CHALLENGE.md path instead.

Fail-open by design: any parsing problem returns 0 (allow) so a hook hiccup can
never wedge the session. Exit 2 is the Claude Code contract for "block this tool
call and show stderr to the model".
"""
import json
import os
import sys

MARKER = "/__tests__/_holdout/"


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:  # noqa: BLE001 — never break the session on a parse hiccup
        return 0

    ti = data.get("tool_input") or {}
    fp = ti.get("file_path") or ti.get("notebook_path") or ""
    if not fp:
        return 0

    cwd = data.get("cwd") or os.getcwd()
    path = fp if os.path.isabs(fp) else os.path.normpath(os.path.join(cwd, fp))
    norm = path.replace("\\", "/")
    if MARKER not in norm:
        return 0  # not a holdout file

    if os.path.basename(norm) == "_CHALLENGE.md":
        return 0  # the governance escape hatch is always allowed

    # .../workspace/apps/<name>/__tests__/_holdout/...  → lock at
    # .../workspace/specs/<name>/holdout.lock
    before = norm.split(MARKER, 1)[0]          # .../workspace/apps/<name>
    parts = before.split("/")
    try:
        apps_i = len(parts) - 1 - parts[::-1].index("apps")
    except ValueError:
        return 0  # unexpected layout → don't block
    if apps_i + 1 >= len(parts):
        return 0
    name = parts[apps_i + 1]
    ws_root = "/".join(parts[:apps_i])         # .../workspace
    lock = os.path.join(ws_root, "specs", name, "holdout.lock")
    if not os.path.isfile(lock):
        return 0  # not locked yet → authoring phase, allow

    sys.stderr.write(
        f"⛔ AREA oracle-loop: the holdout oracle for '{name}' is LOCKED "
        f"({lock}).\n"
        f"Editing a locked holdout destroys its independence and VOIDS the method "
        f"(the same reasoning must never both write AND grade the code).\n"
        f"→ Do NOT modify files under __tests__/_holdout/. Instead:\n"
        f"  1. Fix the IMPLEMENTATION so the locked tests pass; or\n"
        f"  2. If you genuinely believe a holdout test is wrong, write "
        f"__tests__/_holdout/_CHALLENGE.md explaining why and ask Tung, then "
        f"re-lock via tools/lock-holdout.sh.\n"
        f"See CLAUDE.md §1.\n"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
