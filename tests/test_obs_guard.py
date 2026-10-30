"""P1 — obs.log_run must not pollute the real ledger from a test that forgot to redirect
RUNS (the 108-fake-rows bug), and summary() must disclose unknown-cost runs instead of
silently folding them into $0.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from area import obs


def test_guard_skips_write_when_runs_is_the_default(tmp_path: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    # Simulate "a test forgot to redirect RUNS": point RUNS at a path that IS the default
    # (_DEFAULT_RUNS == RUNS). Under pytest with no opt-in, the guard must skip the write —
    # this is the defense-in-depth that stops the real-ledger pollution bug. (The suite's
    # own fixture also redirects RUNS to a tmp; this tests the code guard directly.)
    led = tmp_path / ".area" / "runs.jsonl"
    monkeypatch.setattr(obs, "RUNS", led)
    monkeypatch.setattr(obs, "_DEFAULT_RUNS", led)
    monkeypatch.delenv("AREA_OBS_ALLOW_WRITE", raising=False)
    obs.log_run("test:guard", duration=0.1, cost=0.01, passed=True, name="nonesuch-xyz")
    assert not led.exists(), "guard should skip writing the default/production ledger under pytest"


def test_log_run_writes_a_redirected_ledger(tmp_path: Path,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    led = tmp_path / ".area" / "runs.jsonl"
    monkeypatch.setattr(obs, "RUNS", led)
    obs.log_run("test:redirect", duration=0.1, cost=0.02, passed=True, name="nonesuch-xyz")
    assert led.exists() and "test:redirect" in led.read_text()


def test_opt_in_allows_writing_under_pytest(tmp_path: Path,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    # Even at the default path, an explicit opt-in writes (used by real runs inside CI).
    led = tmp_path / "runs.jsonl"
    monkeypatch.setattr(obs, "RUNS", led)
    monkeypatch.setattr(obs, "_DEFAULT_RUNS", led)  # make it look like production
    monkeypatch.setenv("AREA_OBS_ALLOW_WRITE", "1")
    obs.log_run("test:optin", duration=0.1, cost=0.0, passed=True, name="nonesuch-xyz")
    assert led.exists() and "test:optin" in led.read_text()


def test_summary_discloses_missing_cost() -> None:
    runs = [
        {"label": "a", "duration_s": 1, "cost_usd": 0.1},
        {"label": "b", "duration_s": 1, "cost_usd": None},  # explicitly unknown
        {"label": "c", "duration_s": 1},                    # cost absent
    ]
    s = obs.summary(runs)
    assert s["runs_missing_cost"] == 2
    # total is a lower bound; the known cost still sums correctly
    assert s["total_cost_usd"] == 0.1
