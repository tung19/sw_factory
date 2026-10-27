"""Round-4 arch cleanup — the gate set is a single source (_GATE_ORDER) that
drives _finish selection, _run_gate dispatch, and the --all help. These pin that
every ordered gate actually dispatches (none silently falls through to the
pass-through default) and that the help can't drift from the set."""
from types import SimpleNamespace

import area.cli as CLI
import area.verify as V

_VERIFY_FNS = ("holdout_verify", "static_audit", "e2e_verify", "chaos_verify",
               "nfr_verify", "perf_verify", "visual_verify", "product_verify",
               "cost_verify")


def _args():
    return SimpleNamespace(
        backend="acp", model=None, strict=False, audit_level="high",
        no_block_injection=False, nfr_build=False, perf_requests=200,
        perf_concurrency=10, visual_pixel=False, cost_max=None, _build_start=None)


def test_every_ordered_gate_dispatches(monkeypatch):
    called: list[str] = []
    for fn in _VERIFY_FNS:
        monkeypatch.setattr(V, fn,
                            lambda *a, _fn=fn, **k: (called.append(_fn), True)[1])
    for gate in CLI._GATE_ORDER:
        called.clear()
        assert CLI._run_gate(gate, "app", _args()) is True
        assert called, f"gate {gate!r} fell through to the pass-through default"


def test_all_gates_help_lists_every_gate():
    for gate in CLI._GATE_ORDER:
        assert gate in CLI._ALL_GATES_HELP
    assert "cost" in CLI._ALL_GATES_HELP          # the drift that this fixes


def test_unknown_gate_is_noop_true():
    assert CLI._run_gate("nope", "app", _args()) is True


def test_run_gate_passes_through_per_gate_kwargs(monkeypatch):
    # regression for the refactor: the dict dispatch must still forward each
    # gate's distinctive kwargs (not just call the fn bare)
    seen: dict = {}
    monkeypatch.setattr(V, "cost_verify",
                        lambda name, **kw: seen.update(name=name, **kw) or True)
    args = _args()
    args.strict = True
    args.cost_max = 7.0
    args._build_start = 123.0
    assert CLI._run_gate("cost", "appX", args) is True
    assert seen["name"] == "appX" and seen["strict"] is True
    assert seen["override"] == 7.0 and seen["since"] == 123.0
