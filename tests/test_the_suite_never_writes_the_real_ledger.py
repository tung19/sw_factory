"""A test run must not append to the user's telemetry ledger.

`obs.log_run` writes to `WORKSPACE/.area/runs.jsonl` — the real one, in the real
workspace — and swallows every exception, so a test that drives the genuine
`run_until` or `ask_cli` pollutes it without failing. That is how 86 synthetic
records ended up in a ledger that `area cost` prices and `area evals` uses as a
baseline, carrying the app name of whichever test had last called `set_app`.

These assert the guard in `conftest.py` by OBSERVING the real file, not by
inspecting the fixture: remove the fixture and they go red.
"""
import json

import pytest

from area import obs
from area.paths import WORKSPACE

REAL = WORKSPACE / ".area" / "runs.jsonl"


def _lines(p):
    return len(p.read_text(errors="ignore").splitlines()) if p.exists() else 0


def test_log_run_lands_in_a_temporary_ledger_not_the_real_one():
    assert obs.RUNS != REAL, "the suite is pointed at the user's ledger"
    before = _lines(REAL)
    obs.log_run("probe", duration=0.0, passed=True, backend="test")
    assert _lines(REAL) == before, f"the suite appended to {REAL}"
    assert _lines(obs.RUNS) == 1, "the record went nowhere; the guard broke log_run"
    assert json.loads(obs.RUNS.read_text())["label"] == "probe"


def test_the_real_ledger_survives_the_genuine_adapter_paths():
    """The actual offenders: `run_until` and `ask_cli` log from inside their own
    `try/except pass`, so this is the shape that polluted silently."""
    from area.engine import VerifyResult
    from area.engine import adapter as A

    before = _lines(REAL)

    class _Agent:
        def close(self):
            pass

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(A, "_mk_conversation", lambda *a, **k: object())
        mp.setattr(A, "_send_and_run", lambda conv, msg: None)
        A.run_until(_Agent(), obs.RUNS.parent, "task",
                    lambda: VerifyResult(True, "ok"), max_iters=1)

    assert _lines(REAL) == before, f"run_until appended to {REAL}"
    assert _lines(obs.RUNS) >= 1, "run_until logged nothing at all"


def test_the_app_name_does_not_leak_in_from_an_earlier_test():
    """`set_app` is a process-global. Unreset, every later `log_run` in the same
    process is attributed to that app — which is exactly how test records came to
    look like real runs of a real app."""
    obs.set_app("some-other-test-app")
    obs.log_run("probe-a", duration=0.0)
    assert json.loads(obs.RUNS.read_text().splitlines()[-1])["name"] == \
        "some-other-test-app"
    # the fixture resets it for the NEXT test; prove the reset is what we rely on
    assert obs._current_app == "some-other-test-app"


def test_the_leak_was_reset_before_this_test_ran():
    """Runs after the test above. Ordering-dependent by design: this is the
    assertion that the autouse reset actually happens per test."""
    assert obs._current_app is None, "set_app leaked across tests"
    obs.log_run("probe-b", duration=0.0)
    assert json.loads(obs.RUNS.read_text())["name"] is None
