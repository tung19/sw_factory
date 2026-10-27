"""Audit fix (HIGH): the oracle must confirm the locked suite actually RAN, not
just that the runner exited 0. A builder-controlled vitest config with
passWithNoTests / a non-matching include collects 0 tests and exits 0 — the
locked suite never runs, yet exit-code-only trust would report green."""
import area.verify._runners as R
from area.verify.holdout import _expected_ac_count, _holdout_oracle, _lock


# ---- pure parsers ---------------------------------------------------------------

def test_vitest_passed_parses_summaries():
    assert R.vitest_passed("Tests  12 passed (12)") == 12
    assert R.vitest_passed("Tests  2 failed | 10 passed (12)") == 10
    assert R.vitest_passed("Test Files  1 passed (1)\n Tests  30 passed (30)") == 30
    assert R.vitest_passed("nothing here") is None


def test_playwright_passed_parses():
    assert R.playwright_passed("15 passed (9.2s)") == 15
    assert R.playwright_passed("no summary") is None


def test_assert_vitest_ran_rejects_zero_and_too_few():
    assert R.assert_vitest_ran("No test files found")[0] is False
    assert R.assert_vitest_ran("passWithNoTests: true\nTests  0 passed")[0] is False
    assert R.assert_vitest_ran("Tests  3 passed (3)", 5)[0] is False      # fewer than AC
    assert R.assert_vitest_ran("Tests  5 passed (5)", 5)[0] is True
    assert R.assert_vitest_ran("Tests  8 passed (8)", 5)[0] is True       # ≥ AC
    assert R.assert_vitest_ran("exit 0 but no summary")[0] is False       # fail-closed


def test_assert_playwright_ran():
    assert R.assert_playwright_ran("15 passed (3s)")[0] is True
    assert R.assert_playwright_ran("no tests found")[0] is False


# ---- _expected_ac_count ---------------------------------------------------------

def test_expected_ac_count(tmp_path):
    (tmp_path / "a.test.ts").write_text("describe('AC-1',...); it('AC-2'); AC-2 again; AC-10")
    assert _expected_ac_count(tmp_path) == 3                               # AC-1, AC-2, AC-10


# ---- the oracle integration (no vitest needed — fake the runner output) ---------

def _holdout(tmp_path):
    hd = tmp_path / "__tests__" / "_holdout"
    hd.mkdir(parents=True)
    (hd / "ac.test.ts").write_text("describe('AC-1'); describe('AC-2')")   # expected=2
    return hd


def test_oracle_rejects_green_but_zero_tests(tmp_path):
    hd = _holdout(tmp_path)
    oracle = _holdout_oracle(tmp_path, hd, _lock(hd),
                             cmd=["bash", "-lc", "echo 'No test files found'; exit 0"])
    r = oracle()
    assert r.ok is False and "DID NOT RUN" in r.feedback


def test_oracle_rejects_green_but_too_few_tests(tmp_path):
    hd = _holdout(tmp_path)
    oracle = _holdout_oracle(tmp_path, hd, _lock(hd),
                             cmd=["bash", "-lc", "echo 'Tests  1 passed (1)'; exit 0"])
    assert oracle().ok is False                                            # 1 < 2 AC


def test_oracle_accepts_green_with_enough_tests(tmp_path):
    hd = _holdout(tmp_path)
    oracle = _holdout_oracle(tmp_path, hd, _lock(hd),
                             cmd=["bash", "-lc", "echo 'Tests  2 passed (2)'; exit 0"])
    assert oracle().ok is True


def test_oracle_still_fails_on_nonzero_exit(tmp_path):
    hd = _holdout(tmp_path)
    oracle = _holdout_oracle(tmp_path, hd, _lock(hd),
                             cmd=["bash", "-lc", "echo 'Tests  2 passed (2)'; exit 1"])
    assert oracle().ok is False


def test_oracle_still_rejects_tampered_holdout(tmp_path):
    hd = _holdout(tmp_path)
    lock = _lock(hd)
    (hd / "ac.test.ts").write_text("tampered")                            # change after lock
    oracle = _holdout_oracle(tmp_path, hd, lock,
                             cmd=["bash", "-lc", "echo 'Tests  2 passed (2)'; exit 0"])
    r = oracle()
    assert r.ok is False and "FORBIDDEN" in r.feedback
