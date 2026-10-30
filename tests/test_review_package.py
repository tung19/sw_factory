"""P8 — tools/review-package.sh emits a BASE..HEAD review package and refuses a stale or
empty range (the determinism guards that make it a script, not a prompt)."""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "review-package.sh"


def _git(cwd: Path, *a: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True)


def _run(cwd: Path, *a: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(TOOL), *a], cwd=cwd, capture_output=True, text=True)


def _repo(d: Path) -> tuple[str, str]:
    _git(d, "init", "-q")
    _git(d, "config", "user.email", "t@e")
    _git(d, "config", "user.name", "t")
    (d / "a.txt").write_text("1\n")
    _git(d, "add", "."); _git(d, "commit", "-qm", "base")
    base = _git(d, "rev-parse", "HEAD").stdout.strip()
    (d / "a.txt").write_text("1\n2\n")
    _git(d, "add", "."); _git(d, "commit", "-qm", "change")
    head = _git(d, "rev-parse", "HEAD").stdout.strip()
    return base, head


def test_emits_commits_and_diff(tmp_path: Path) -> None:
    base, head = _repo(tmp_path)
    r = _run(tmp_path, base, head)
    assert r.returncode == 0, r.stderr
    assert "## Commits" in r.stdout and "change" in r.stdout
    assert "## Diff (-U10)" in r.stdout and "a.txt" in r.stdout


def test_empty_range_is_rejected(tmp_path: Path) -> None:
    _, head = _repo(tmp_path)
    r = _run(tmp_path, head, head)
    assert r.returncode == 3 and "empty range" in r.stderr


def test_non_descendant_range_is_rejected(tmp_path: Path) -> None:
    # reversed args: base is NEWER than head, so head is not a descendant of base.
    base, head = _repo(tmp_path)
    r = _run(tmp_path, head, base)  # BASE=head, HEAD=base
    assert r.returncode == 3 and "not a descendant" in r.stderr


def test_bad_rev_is_a_usage_error(tmp_path: Path) -> None:
    base, _ = _repo(tmp_path)
    r = _run(tmp_path, base, "deadbeef")
    assert r.returncode == 2 and "not a commit" in r.stderr
