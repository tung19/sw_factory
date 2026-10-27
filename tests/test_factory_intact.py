"""The factory's own code must not change while a run is in progress.

Group 3 / item 9 of docs/secure-factory-gap-assessment.md. The holdout lock protects
the ORACLE from the builder; this protects the FACTORY from it. Pure logic: the shell
script on a fake checkout, plus the CLI helpers with a stubbed subprocess.
"""
import argparse
import os
import shutil
import subprocess
from pathlib import Path

import area.cli as C

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "verify-factory-intact.sh"


def _fake_checkout(root: Path) -> Path:
    """A minimal tree with the shapes the script checksums."""
    (root / "tools").mkdir(parents=True)
    (root / "area" / "verify").mkdir(parents=True)
    (root / "skills" / "s1").mkdir(parents=True)
    (root / ".claude").mkdir(parents=True)
    (root / "area" / "verify" / "audit.py").write_text("def check(): return True\n")
    (root / "area" / "cli.py").write_text("x = 1\n")
    (root / "skills" / "s1" / "SKILL.md").write_text("# skill\n")
    (root / ".claude" / "settings.json").write_text("{}\n")
    shutil.copy2(SCRIPT, root / "tools" / "verify-factory-intact.sh")
    return root


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(root / "tools" / "verify-factory-intact.sh"), *args],
        capture_output=True, text=True, cwd=str(root), timeout=60)


def test_snapshot_then_verify_is_clean(tmp_path):
    root = _fake_checkout(tmp_path / "repo")
    lock = tmp_path / "f.lock"
    assert _run(root, "snapshot", str(lock)).returncode == 0
    assert lock.exists() and lock.read_text().strip()
    r = _run(root, "verify", str(lock))
    assert r.returncode == 0 and "intact" in r.stdout


def test_a_modified_gate_checker_fails_and_is_named(tmp_path):
    """The worst case: the thing that GRADES the build is edited mid-run."""
    root = _fake_checkout(tmp_path / "repo")
    lock = tmp_path / "f.lock"
    _run(root, "snapshot", str(lock))
    (root / "area" / "verify" / "audit.py").write_text("def check(): return True  # :)\n")
    r = _run(root, "verify", str(lock))
    assert r.returncode == 1
    assert "FACTORY CHANGED" in r.stderr and "audit.py" in r.stderr


def test_added_and_removed_files_are_caught(tmp_path):
    root = _fake_checkout(tmp_path / "repo")
    lock = tmp_path / "f.lock"
    _run(root, "snapshot", str(lock))
    (root / "area" / "injected.py").write_text("import os\n")
    assert _run(root, "verify", str(lock)).returncode == 1

    root2 = _fake_checkout(tmp_path / "repo2")
    lock2 = tmp_path / "f2.lock"
    _run(root2, "snapshot", str(lock2))
    (root2 / "skills" / "s1" / "SKILL.md").unlink()
    assert _run(root2, "verify", str(lock2)).returncode == 1


def test_pyc_and_pycache_do_not_trip_it(tmp_path):
    """A run legitimately writes bytecode; that is not a source change."""
    root = _fake_checkout(tmp_path / "repo")
    lock = tmp_path / "f.lock"
    _run(root, "snapshot", str(lock))
    (root / "area" / "__pycache__").mkdir()
    (root / "area" / "__pycache__" / "cli.cpython-312.pyc").write_bytes(b"\x00\x01")
    (root / "area" / "stray.pyc").write_bytes(b"\x00")
    assert _run(root, "verify", str(lock)).returncode == 0


def test_missing_lock_is_usage_not_tamper(tmp_path):
    """Exit 2, so the CLI records "not checked" rather than "changed"."""
    root = _fake_checkout(tmp_path / "repo")
    r = _run(root, "verify", str(tmp_path / "nope.lock"))
    assert r.returncode == 2 and "no factory snapshot" in r.stderr


def test_script_works_on_a_partial_checkout(tmp_path):
    """A clone may legitimately have no skills/ or .claude/settings.json."""
    root = tmp_path / "repo"
    (root / "area").mkdir(parents=True)
    (root / "tools").mkdir(parents=True)
    (root / "area" / "cli.py").write_text("x = 1\n")
    shutil.copy2(SCRIPT, root / "tools" / "verify-factory-intact.sh")
    lock = tmp_path / "f.lock"
    assert _run(root, "snapshot", str(lock)).returncode == 0
    assert _run(root, "verify", str(lock)).returncode == 0


# ---- CLI wiring ---------------------------------------------------------------
def test_cli_snapshot_puts_the_lock_outside_the_workspace(tmp_path, monkeypatch):
    """The lock must not live where the agent writes, or it could be rewritten to
    match the tampered tree."""
    args = argparse.Namespace(cmd="run")
    C._factory_snapshot(args)
    lock = getattr(args, "_factory_lock", None)
    assert lock, "snapshot did not produce a lock on a real checkout"
    assert "workspace" not in lock
    from area.paths import REPO

    assert REPO not in Path(lock).parents
    assert C._factory_verify(args) is True
    assert not Path(lock).exists()  # cleaned up after verifying


def test_cli_verify_reports_not_checked_when_there_is_no_lock():
    """None, never True — provenance must not imply a check that did not run."""
    assert C._factory_verify(argparse.Namespace()) is None
    assert C._factory_verify(argparse.Namespace(_factory_lock=None)) is None


def test_only_agent_running_commands_are_guarded():
    assert set(C._FACTORY_GUARDED) <= set(C._HANDLERS)
    for cmd in ("run", "clone", "intake", "iterate"):
        assert cmd in C._FACTORY_GUARDED
    # read-only/report commands don't need a snapshot
    for cmd in ("doctor", "obs", "provenance", "trace"):
        assert cmd not in C._FACTORY_GUARDED


def test_cli_verify_maps_a_real_tamper_to_False(tmp_path, monkeypatch):
    """Exit 1 from the script must become False (block), not None (not checked)."""
    args = argparse.Namespace()
    args._factory_lock = str(tmp_path / "f.lock")

    def _fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, "", "FACTORY CHANGED ... area/x.py")

    monkeypatch.setattr(C.subprocess, "run", _fake_run)
    assert C._factory_verify(args) is False


def test_doctor_flags_a_workspace_inside_the_repo(monkeypatch):
    import area.doctor as D

    monkeypatch.delenv("AREA_WORKSPACE", raising=False)
    name, status, detail, fix = D.check_workspace()
    assert name == "workspace" and status == "warn" and "INSIDE" in detail
    assert "AREA_WORKSPACE" in fix

    monkeypatch.setenv("AREA_WORKSPACE", os.path.expanduser("~/area-generated-test"))
    name, status, detail, _ = D.check_workspace()
    assert status == "ok" and "outside" in detail
    assert ("workspace", "warn") != (name, status)


def test_doctor_report_includes_the_workspace_check():
    import area.doctor as D

    assert "workspace" in [c[0] for c in D.report()]
