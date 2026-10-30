"""P11 — tools/check-no-fixed-sleeps.sh flags fixed sleeps in generated tests."""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "check-no-fixed-sleeps.sh"


def _run(d: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(TOOL), str(d)], capture_output=True, text=True)


def test_flags_waitfortimeout(tmp_path: Path) -> None:
    (tmp_path / "login.spec.ts").write_text("await page.waitForTimeout(500);\n")
    r = _run(tmp_path)
    assert r.returncode == 1 and "fixed sleeps" in r.stderr and "login.spec.ts" in r.stderr


def test_flags_time_sleep(tmp_path: Path) -> None:
    (tmp_path / "chaos_test.py").write_text("import time\ntime.sleep(2)\n")
    r = _run(tmp_path)
    assert r.returncode == 1 and "chaos_test.py" in r.stderr


def test_passes_on_condition_based_wait(tmp_path: Path) -> None:
    (tmp_path / "ok.spec.ts").write_text(
        "await expect(page.getByText('charged')).toBeVisible({ timeout: 5000 });\n")
    r = _run(tmp_path)
    assert r.returncode == 0 and "no fixed sleeps" in r.stdout


def test_missing_dir_is_usage_error(tmp_path: Path) -> None:
    r = _run(tmp_path / "nope")
    assert r.returncode == 2
