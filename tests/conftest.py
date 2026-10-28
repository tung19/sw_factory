"""Dogfood test suite for AREA itself (the orchestrator).

These tests cover AREA's own pure logic — the anti-self-certification lock, the
TDD build/challenge ordering, name sanitization, the experience store — WITHOUT
running any live agent (no ACP/OpenHands/npm/network). The agent-driven stages
are stubbed; what we assert here is the orchestration policy AREA is responsible
for, which is exactly where bugs would silently weaken the "oracle".
"""
import os

import pytest

os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")


# ---------------------------------------------------------------------------
# The telemetry ledger is PRODUCTION STATE, not a fixture.
#
# `obs.RUNS` is `WORKSPACE/.area/runs.jsonl` in the user's real workspace, and
# `log_run` is wrapped in `except Exception: pass`, so a test that drives the real
# `run_until`/`ask_cli` appends to it SILENTLY and still passes. Three such records
# per suite run is not a rounding error: 86 of them accumulated here, and because
# `_current_app` is a process-global that no test reset, they inherited the app name
# of whichever test had last called `set_app` — so they read as real agent runs on a
# real app. They were then used to answer a question about money, and to compute
# `cost` gate coverage. Fake runs in the ledger are not noise; they are wrong answers.
#
# Autouse, so it covers the tests that exist and the ones written later. A test that
# wants to assert on ledger contents overrides `obs.RUNS` itself, which still works.
@pytest.fixture(autouse=True)
def _ledger_is_never_the_users(tmp_path, monkeypatch):
    from area import obs

    monkeypatch.setattr(obs, "RUNS", tmp_path / ".area" / "runs.jsonl")
    monkeypatch.setattr(obs, "_current_app", None)   # process-global; leaks otherwise

    # The memory store is the same hazard and strictly worse: `obs.RUNS` only
    # feeds a gate, while `memory.MEM` is injected into the TOP of later build
    # prompts. Nothing writes it from the suite today, but only because
    # `remember()` needs a fix and no current test supplies one — a test of the
    # retry path would have poisoned real prompts. docs/harness2-gap-assessment.md F5.
    from area.memory import store as _mem

    monkeypatch.setattr(_mem, "MEM", tmp_path / ".area" / "memory.jsonl")
