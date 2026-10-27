"""The shell tools CLAUDE.md prescribes must look where the apps actually are.

Generated apps live in AREA_WORKSPACE (`~/area-generated` by default), outside the repo.
Three scripts defaulted to a repo-relative `workspace/` and therefore failed when run
exactly as the rules prescribe — each with a message that blamed the operator:

  * `tools/gate.sh <app> --e2e` -> "chưa có e2e/ — hãy tự viết Playwright specs",
    while 12 specs sat in the real app directory. `--e2e` is MANDATORY for an
    auth/session/form app (CLAUDE.md step 3).
  * `tools/lock-holdout.sh <app>` (CLAUDE.md step 1b) -> "không thấy holdout — hãy viết
    test holdout (từ spec) trước", while the locked oracle was right there.
  * `tools/verify-holdout-intact.sh <app>` (CLAUDE.md step 2, "before and after each
    build attempt") -> the same.

The Python callers always passed the workspace explicitly, so the engine was fine. It
was the documented MANUAL path — the checksum enforcement the whole method rests on —
that was broken.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from area.paths import REPO

HOLDOUT = "__tests__/_holdout"


def _run(script: str, *args: str, cwd: Path = REPO) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(REPO / "tools" / script), *args],
                          capture_output=True, text=True, cwd=str(cwd), timeout=120)


@pytest.fixture
def ws(tmp_path):
    """A throwaway workspace laid out the way AREA lays one out."""
    app = tmp_path / "apps" / "t" / HOLDOUT
    app.mkdir(parents=True)
    (tmp_path / "specs" / "t").mkdir(parents=True)
    (app / "ac1.test.ts").write_text("it('AC-1', () => {})\n")
    return tmp_path


def test_lock_then_verify_round_trips(ws):
    assert _run("lock-holdout.sh", "t", str(ws)).returncode == 0
    assert (ws / "specs" / "t" / "holdout.lock").read_text().strip()
    assert _run("verify-holdout-intact.sh", "t", str(ws)).returncode == 0


def test_a_changed_holdout_is_detected(ws):
    _run("lock-holdout.sh", "t", str(ws))
    (ws / "apps" / "t" / HOLDOUT / "ac1.test.ts").write_text(
        "it('AC-1', () => {})\nit('snuck in', () => {})\n")
    r = _run("verify-holdout-intact.sh", "t", str(ws))
    assert r.returncode == 1 and "BỊ ĐỔI" in r.stdout + r.stderr


def test_a_file_ADDED_to_the_locked_dir_is_detected(ws):
    """Not just edits: slipping an extra test in is tampering too."""
    _run("lock-holdout.sh", "t", str(ws))
    (ws / "apps" / "t" / HOLDOUT / "extra.test.ts").write_text("it('extra', () => {})\n")
    assert _run("verify-holdout-intact.sh", "t", str(ws)).returncode == 1


def test_the_default_workspace_is_areas_not_the_repos(ws, monkeypatch):
    """The regression itself: with NO second argument the script must resolve
    AREA_WORKSPACE, not `./workspace`. Proven by pointing AREA_WORKSPACE at a tree the
    repo-relative default could never find."""
    monkeypatch.setenv("AREA_WORKSPACE", str(ws))
    assert _run("lock-holdout.sh", "t").returncode == 0, "did not find the real workspace"
    assert _run("verify-holdout-intact.sh", "t").returncode == 0

    # ... and it still reports tampering through that same resolved path
    (ws / "apps" / "t" / HOLDOUT / "ac1.test.ts").write_text("it('changed', () => {})\n")
    assert _run("verify-holdout-intact.sh", "t").returncode == 1


def test_no_tool_script_defaults_to_a_repo_relative_workspace():
    """A guard for the next script: the literal default that caused this must not
    come back. (Comments explaining the bug are fine; the shell default is not.)"""
    bad = []
    for f in sorted((REPO / "tools").glob("*.sh")):
        for i, line in enumerate(f.read_text().splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if '${2:-workspace}' in stripped or '="workspace"' in stripped:
                bad.append(f"{f.name}:{i}")
    assert not bad, f"repo-relative workspace default(s): {bad}"


def test_gate_sh_rejects_an_unknown_flag_instead_of_ignoring_it():
    """`--chaos` used to be silently dropped, which is why the flag parser now fails
    closed. A typo must not read as "that gate ran"."""
    r = _run("gate.sh", "whatever", "--chaoss")
    assert r.returncode == 2 and "unknown option" in r.stderr


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_gate_sh_resolves_the_app_through_area_paths(tmp_path, monkeypatch):
    """It must look in AREA_WORKSPACE, and say so clearly when the app is absent."""
    env = dict(os.environ, AREA_WORKSPACE=str(tmp_path))
    r = subprocess.run(["bash", str(REPO / "tools" / "gate.sh"), "ghost"],
                       capture_output=True, text=True, cwd=str(REPO), env=env, timeout=120)
    assert r.returncode == 2
    assert str(tmp_path) in r.stderr, r.stderr
