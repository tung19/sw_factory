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


# ---- the condition CI exposed and the local run could not --------------------

def _tools_copy(tmp_path: Path) -> Path:
    """A checkout of `tools/` with NO `.venv` beside it — what CI actually has, and
    what a fresh clone has before `make install`."""
    dst = tmp_path / "checkout"
    dst.mkdir()
    shutil.copytree(REPO / "tools", dst / "tools")
    assert not (dst / ".venv").exists()
    return dst


def test_resolution_survives_a_checkout_with_no_venv(tmp_path):
    """The first version of this fix asked `.venv/bin/python` for the workspace and fell
    back to the literal `workspace/` when that was missing — so wherever there was no
    venv it silently reverted to the bug it was fixing. The local suite could not catch
    that, because the local checkout HAS a venv; CI did. The resolver is pure shell now."""
    checkout = _tools_copy(tmp_path)
    ws = tmp_path / "ws"
    (ws / "apps" / "t" / HOLDOUT).mkdir(parents=True)
    (ws / "specs" / "t").mkdir(parents=True)
    (ws / "apps" / "t" / HOLDOUT / "ac1.test.ts").write_text("it('AC-1', () => {})\n")

    env = dict(os.environ, AREA_WORKSPACE=str(ws))
    for script in ("lock-holdout.sh", "verify-holdout-intact.sh"):
        r = subprocess.run(["bash", str(checkout / "tools" / script), "t"],
                           capture_output=True, text=True, env=env, cwd="/", timeout=120)
        assert r.returncode == 0, f"{script}: {r.stdout}{r.stderr}"
    assert (ws / "specs" / "t" / "holdout.lock").read_text().strip()


def test_the_default_is_anchored_on_the_script_not_on_the_caller_cwd(tmp_path):
    """`lock-holdout.sh` and `verify-holdout-intact.sh` do not cd to the repo root, so a
    `$PWD`-relative default would mean a different directory depending on where the
    operator happened to stand."""
    checkout = _tools_copy(tmp_path)
    env = {k: v for k, v in os.environ.items() if k != "AREA_WORKSPACE"}
    r = subprocess.run(["bash", str(checkout / "tools" / "verify-holdout-intact.sh"), "t"],
                       capture_output=True, text=True, env=env, cwd="/", timeout=120)
    out = r.stdout + r.stderr
    assert str(checkout / "workspace") in out, out
    assert "/workspace/specs" in out


def test_gate_sh_reports_a_missing_app_before_it_needs_a_python(tmp_path):
    """It used to exit 127 ("`.venv/bin/python`: No such file or directory") where it
    meant "no such app". The workspace is resolved in shell, so the usage error comes
    first."""
    checkout = _tools_copy(tmp_path)
    env = dict(os.environ, AREA_WORKSPACE=str(tmp_path / "nowhere"))
    r = subprocess.run(["bash", str(checkout / "tools" / "gate.sh"), "ghost"],
                       capture_output=True, text=True, env=env, cwd="/", timeout=120)
    assert r.returncode == 2, f"{r.returncode}: {r.stderr}"
    assert "no app at" in r.stderr and "nowhere" in r.stderr


def test_the_resolver_asks_no_interpreter(tmp_path):
    """A guard for the regression itself: the workspace resolution must not depend on an
    interpreter being present, or it will quietly fall back again."""
    src = (REPO / "tools" / "_workspace.sh").read_text()
    # The function BODY only — the file's header comment legitimately explains the bug
    # by naming `.venv/bin/python`, and `area_python()` below is allowed to use it.
    body = src.split("\narea_workspace() {", 1)[1].split("\n}", 1)[0]
    for forbidden in (".venv/bin/python", "python3", "python "):
        assert forbidden not in body, f"area_workspace() depends on {forbidden!r}"
