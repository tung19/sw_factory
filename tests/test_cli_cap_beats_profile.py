"""B7 (deep audit 2026-10-28): the CLI --budget/--agent-iters must beat a profile default.

The CLI flags are delivered via env (AREA_MAX_BUDGET / AREA_AGENT_ITERS). run_once and
run_until applied the per-kind PROFILE default before _mk_conversation read the env, so the
moment a profile set budget_usd/agent_iters the operator's --budget was silently ignored —
inverting the documented "a CLI flag always wins" and weakening a cost cap. Precedence must
be: explicit kwarg > CLI flag (env) > profile default > global default.
"""
import types

import area.engine.adapter as A


def _spy(monkeypatch):
    seen: dict = {}

    def mk(agent, ws, agent_iters, budget):
        seen["agent_iters"], seen["budget"] = agent_iters, budget
        return object()

    monkeypatch.setattr(A, "_mk_conversation", mk)
    monkeypatch.setattr(A, "_send_and_run", lambda conv, msg: None)
    monkeypatch.setattr(A, "_profile_defaults",
                        lambda label: {"budget_usd": 5.0, "agent_iters": 99})
    return seen


def test_cap_helper_precedence(monkeypatch):
    monkeypatch.setenv("AREA_MAX_BUDGET", "2.0")
    assert A._cap(None, "AREA_MAX_BUDGET", 5.0, float) == 2.0   # env beats profile
    assert A._cap(7.0, "AREA_MAX_BUDGET", 5.0, float) == 7.0    # explicit beats env
    monkeypatch.delenv("AREA_MAX_BUDGET", raising=False)
    assert A._cap(None, "AREA_MAX_BUDGET", 5.0, float) == 5.0   # profile when no flag
    assert A._cap(None, "AREA_MAX_BUDGET", None, float) is None


def test_run_once_cli_budget_beats_profile(monkeypatch, tmp_path):
    monkeypatch.setenv("AREA_MAX_BUDGET", "2.0")
    seen = _spy(monkeypatch)
    A.run_once(object(), tmp_path, "msg", label="builder")
    assert seen["budget"] == 2.0, "profile shadowed the CLI --budget in run_once"


def test_run_until_cli_budget_beats_profile(monkeypatch, tmp_path):
    monkeypatch.setenv("AREA_MAX_BUDGET", "2.0")
    seen = _spy(monkeypatch)
    ok = types.SimpleNamespace(ok=True, feedback="")
    A.run_until(object(), tmp_path, "task", lambda: ok, label="builder")
    assert seen["budget"] == 2.0, "profile shadowed the CLI --budget in run_until"


def test_profile_budget_used_without_cli_flag(monkeypatch, tmp_path):
    monkeypatch.delenv("AREA_MAX_BUDGET", raising=False)
    seen = _spy(monkeypatch)
    A.run_once(object(), tmp_path, "msg", label="builder")
    assert seen["budget"] == 5.0, "profile default should apply when no CLI flag is set"
