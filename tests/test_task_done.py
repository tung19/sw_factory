"""P3 — tools/task-done.sh records a build milestone ONLY on a green verify command
(compaction-proof resume ledger). The green-only property is the anti-cheat: a milestone
cannot be marked done by narration, only by a command that exits 0.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "task-done.sh"


def _run(ws: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "AREA_WORKSPACE": str(ws)}
    return subprocess.run(["bash", str(TOOL), *args],
                          capture_output=True, text=True, env=env)


def test_records_only_on_green(tmp_path: Path) -> None:
    app = tmp_path / "apps" / "demo"
    app.mkdir(parents=True)
    ledger = app / ".area" / "progress.md"

    # failing verify → non-zero exit, nothing recorded
    r = _run(tmp_path, "demo", "build-green", "--", "false")
    assert r.returncode != 0
    assert not ledger.exists(), "a failed verify must not record a milestone"

    # passing verify → recorded
    r = _run(tmp_path, "demo", "build-green", "--", "true")
    assert r.returncode == 0, r.stderr
    assert ledger.exists() and "build-green" in ledger.read_text()

    # --show prints the ledger
    r = _run(tmp_path, "demo", "--show")
    assert "build-green" in r.stdout


def test_missing_app_dir_is_a_usage_error(tmp_path: Path) -> None:
    r = _run(tmp_path, "ghost", "m", "--", "true")
    assert r.returncode == 2 and "no app at" in r.stderr


def test_show_on_empty_is_quiet(tmp_path: Path) -> None:
    app = tmp_path / "apps" / "demo"
    app.mkdir(parents=True)
    r = _run(tmp_path, "demo", "--show")
    assert r.returncode == 0 and r.stdout.strip() == ""
