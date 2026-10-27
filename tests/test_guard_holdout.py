"""tools/hooks/guard_holdout.py — the PreToolUse hook that HARD-blocks edits to a
LOCKED holdout oracle. Driven here through the real script entrypoint (the way
Claude Code runs it): JSON on stdin, exit 2 = block, exit 0 = allow."""
import json
import os
import subprocess
import sys
from pathlib import Path

GUARD = Path(__file__).resolve().parents[1] / "tools" / "hooks" / "guard_holdout.py"


def _run(tool_input: dict, cwd: str, *, raw: str | None = None) -> int:
    payload = raw if raw is not None else json.dumps({"cwd": cwd, "tool_input": tool_input})
    p = subprocess.run([sys.executable, "-I", str(GUARD)], input=payload,
                       capture_output=True, text=True)
    return p.returncode


def _ws(tmp_path: Path, name: str = "app1", *, locked: bool) -> Path:
    """Build workspace/apps/<name>/__tests__/_holdout + optional specs lock."""
    hold = tmp_path / "workspace" / "apps" / name / "__tests__" / "_holdout"
    hold.mkdir(parents=True)
    (hold / "ac.test.ts").write_text("test('x', () => {});\n")
    if locked:
        spec = tmp_path / "workspace" / "specs" / name
        spec.mkdir(parents=True)
        (spec / "holdout.lock").write_text("deadbeef  ./ac.test.ts\n")
    return tmp_path


def test_locked_holdout_is_blocked(tmp_path):
    _ws(tmp_path, locked=True)
    fp = tmp_path / "workspace/apps/app1/__tests__/_holdout/ac.test.ts"
    assert _run({"file_path": str(fp)}, str(tmp_path)) == 2


def test_unlocked_holdout_is_allowed(tmp_path):
    _ws(tmp_path, locked=False)  # authoring phase, no lock yet
    fp = tmp_path / "workspace/apps/app1/__tests__/_holdout/ac.test.ts"
    assert _run({"file_path": str(fp)}, str(tmp_path)) == 0


def test_challenge_md_is_allowed_even_when_locked(tmp_path):
    _ws(tmp_path, locked=True)
    fp = tmp_path / "workspace/apps/app1/__tests__/_holdout/_CHALLENGE.md"
    assert _run({"file_path": str(fp)}, str(tmp_path)) == 0


def test_product_source_is_allowed(tmp_path):
    _ws(tmp_path, locked=True)
    fp = tmp_path / "workspace/apps/app1/lib/store.ts"
    assert _run({"file_path": str(fp)}, str(tmp_path)) == 0


def test_relative_path_resolved_against_cwd_and_blocked(tmp_path):
    _ws(tmp_path, locked=True)
    app = tmp_path / "workspace/apps/app1"
    assert _run({"file_path": "__tests__/_holdout/ac.test.ts"}, str(app)) == 2


def test_symlink_that_hides_the_marker_is_still_blocked(tmp_path):
    """realpath must defeat a symlink whose lexical path lacks __tests__/_holdout/."""
    _ws(tmp_path, locked=True)
    app = tmp_path / "workspace/apps/app1"
    sneaky = app / "sneaky"
    os.symlink(app / "__tests__" / "_holdout", sneaky)
    assert _run({"file_path": str(sneaky / "ac.test.ts")}, str(tmp_path)) == 2


def test_app_literally_named_apps_is_guarded(tmp_path):
    _ws(tmp_path, name="apps", locked=True)
    fp = tmp_path / "workspace/apps/apps/__tests__/_holdout/ac.test.ts"
    assert _run({"file_path": str(fp)}, str(tmp_path)) == 2


def test_notebook_path_field_is_honored(tmp_path):
    _ws(tmp_path, locked=True)
    fp = tmp_path / "workspace/apps/app1/__tests__/_holdout/ac.test.ts"
    assert _run({"notebook_path": str(fp)}, str(tmp_path)) == 2


def test_malformed_stdin_fails_open(tmp_path):
    assert _run({}, str(tmp_path), raw="this is not json") == 0


def test_empty_input_is_allowed(tmp_path):
    assert _run({}, str(tmp_path)) == 0
