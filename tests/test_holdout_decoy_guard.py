"""A green exit with the locked suite never collected.

vitest's positional argument is a case-insensitive SUBSTRING match on the path relative
to the project root, and it only narrows what `include`/`exclude` already globbed
(v5 `filterFiles`). So ONE line in the builder-owned `vitest.config.ts` —

    exclude: ['**/node_modules/**', '**/__tests__/_holdout/**']

— evicts the locked suite before filtering, while a decoy directory whose name merely
CONTAINS the locked path is still collected by the oracle's own
`npx vitest run __tests__/_holdout`.

Reproduced against real vitest 5.0.5 before the fix: exit 0, no "no test files found",
3 decoy tests passed, and the real locked test (which FAILED) never ran — so the oracle
reported green with zero locked tests executed. That defeats the whole spine, since
every other guard (the checksum lock, the PreToolUse hook, the passed-count assertion)
was satisfied: nothing was tampered with, the tests simply did not run.

The guard is an assertion about OUTCOME — which files the runner reports having
executed — because configuration is the thing the builder controls.
"""
import json

import pytest

import area.verify.holdout as H
from area.verify._runners import assert_locked_files_ran, executed_test_files


def _report(tmp_path, *abs_files):
    """A vitest `--reporter=json` report naming the files it executed."""
    p = tmp_path / "report.json"
    p.write_text(json.dumps({
        "success": True, "numPassedTests": 3 * len(abs_files),
        "testResults": [{"name": str(f), "status": "passed"} for f in abs_files],
    }))
    return p


@pytest.fixture
def holdout(tmp_path):
    hd = tmp_path / "__tests__" / "_holdout"
    hd.mkdir(parents=True)
    (hd / "ac1.test.ts").write_text("it('AC-1', () => {})\n")
    (hd / "ac2.test.ts").write_text("it('AC-2', () => {})\n")
    return hd


def test_a_name_colliding_decoy_cannot_stand_in_for_the_locked_files(tmp_path, holdout):
    decoy = tmp_path / "__tests__" / "_holdout_decoy" / "ac1.test.ts"
    ok, why = assert_locked_files_ran(_report(tmp_path, decoy), holdout, H._lock(holdout))
    assert ok is False
    assert "never executed" in why and "2 of 2" in why


def test_one_locked_file_running_is_not_enough(tmp_path, holdout):
    ok, why = assert_locked_files_ran(
        _report(tmp_path, holdout / "ac1.test.ts"), holdout, H._lock(holdout))
    assert ok is False and "ac2.test.ts" in why


def test_the_honest_case_passes(tmp_path, holdout):
    rep = _report(tmp_path, holdout / "ac1.test.ts", holdout / "ac2.test.ts")
    ok, why = assert_locked_files_ran(rep, holdout, H._lock(holdout))
    assert ok is True and "2 locked file(s) executed" in why


def test_extra_files_alongside_the_locked_ones_are_fine(tmp_path, holdout):
    """The app's own tests may run too; what matters is that the LOCKED ones did."""
    rep = _report(tmp_path, holdout / "ac1.test.ts", holdout / "ac2.test.ts",
                  tmp_path / "src" / "unit.test.ts")
    assert assert_locked_files_ran(rep, holdout, H._lock(holdout))[0] is True


def test_a_missing_or_corrupt_report_fails_rather_than_passes(tmp_path, holdout):
    """The point is to stop trusting a green exit code, so "cannot confirm" is a FAIL."""
    missing = tmp_path / "nope.json"
    ok, why = assert_locked_files_ran(missing, holdout, H._lock(holdout))
    assert ok is False and "no machine-readable report" in why

    corrupt = tmp_path / "bad.json"
    corrupt.write_text("{not json")
    assert assert_locked_files_ran(corrupt, holdout, H._lock(holdout))[0] is False
    assert executed_test_files(corrupt) is None


def test_the_oracle_is_wired_to_the_guard(tmp_path, holdout, monkeypatch):
    """End-to-end through `_holdout_oracle`, without node: a runner that exits 0 with a
    plausible summary but a report naming only a decoy must NOT be believed."""
    app = tmp_path
    (app / "__tests__" / "_holdout_decoy").mkdir(parents=True)
    decoy = app / "__tests__" / "_holdout_decoy" / "ac1.test.ts"
    summary = "\n Test Files  1 passed (1)\n      Tests  3 passed (3)\n"

    def fake_run(cmd, **kw):
        # the oracle passes its own report path on the command line; honour it
        out = next(a for a in cmd[-1].split() if a.startswith("--outputFile.json="))
        path = out.split("=", 1)[1].strip("'\"")
        _report_at(path, decoy)
        return _Completed(summary)

    monkeypatch.setattr(H.subprocess, "run", fake_run)
    r = H._holdout_oracle(app, holdout, H._lock(holdout))()
    assert r.ok is False
    assert "ORACLE DID NOT RUN" in r.feedback and "never executed" in r.feedback

    # ... and the same runner reporting the LOCKED files is believed
    def honest_run(cmd, **kw):
        out = next(a for a in cmd[-1].split() if a.startswith("--outputFile.json="))
        _report_at(out.split("=", 1)[1].strip("'\""),
                   holdout / "ac1.test.ts", holdout / "ac2.test.ts")
        return _Completed(summary)

    monkeypatch.setattr(H.subprocess, "run", honest_run)
    assert H._holdout_oracle(app, holdout, H._lock(holdout))().ok is True


class _Completed:
    returncode = 0

    def __init__(self, out):
        self.stdout, self.stderr = out, ""


def _report_at(path, *abs_files):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"success": True, "numPassedTests": 3,
                   "testResults": [{"name": str(f), "status": "passed"} for f in abs_files]}, fh)
