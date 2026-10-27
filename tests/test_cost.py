"""area.verify.cost — the hard cost-cap gate. Pure cost-summing (precise `since`
window + the standalone session-gap heuristic), cap resolution (committed /
override / default), the pass/over-blocking/over-advisory/skip verdicts, and the
_run_gate dispatch. No obs file or agent is touched — `runs` is injected and
build_cost is monkeypatched for the verdict tests."""
from types import SimpleNamespace

import area.cli as CLI
import area.verify.cost as C


def _runs(*pairs):
    """pairs of (ts, cost_usd) → obs-style run records."""
    return [{"ts": ts, "cost_usd": cost, "label": "build"} for ts, cost in pairs]


# ---- build_cost: precise `since` window -----------------------------------------

def test_build_cost_since_sums_only_the_window():
    runs = _runs((100.0, 1.0), (200.0, 2.0), (300.0, 3.0))
    assert C.build_cost(since=150.0, runs=runs) == 5.0   # 2.0 + 3.0 (ts >= 150)
    assert C.build_cost(since=0.0, runs=runs) == 6.0      # all
    assert C.build_cost(since=999.0, runs=runs) == 0.0    # none


def test_build_cost_ignores_null_cost_rows():
    runs = _runs((100.0, 1.0)) + [{"ts": 110.0, "cost_usd": None, "label": "author"}]
    assert C.build_cost(since=0.0, runs=runs) == 1.0


# ---- build_cost: standalone session-gap heuristic -------------------------------

def test_build_cost_session_sums_trailing_cluster():
    # two sessions: an old one at t≈0, a recent one at t≈10000 (> 30min gap)
    runs = _runs((0.0, 9.0), (100.0, 9.0),
                 (10_000.0, 1.0), (10_100.0, 2.0), (10_200.0, 3.0))
    assert C.build_cost(runs=runs) == 6.0   # only the recent cluster (1+2+3)


def test_build_cost_no_cost_is_zero():
    assert C.build_cost(runs=[]) == 0.0
    assert C.build_cost(runs=[{"ts": 1.0, "cost_usd": None}]) == 0.0


# ---- load_cap -------------------------------------------------------------------

def test_load_cap_default_is_advisory(tmp_path):
    cap, blocking = C.load_cap("app1", strict=False, root=tmp_path)
    assert cap == C.DEFAULT_MAX_USD and blocking is False


def test_load_cap_strict_blocks_default(tmp_path):
    cap, blocking = C.load_cap("app1", strict=True, root=tmp_path)
    assert cap == C.DEFAULT_MAX_USD and blocking is True


def test_load_cap_override_blocks(tmp_path):
    cap, blocking = C.load_cap("app1", strict=False, override=4.0, root=tmp_path)
    assert cap == 4.0 and blocking is True


def test_load_cap_committed_yaml_blocks(tmp_path):
    spec = tmp_path / "specs" / "app1"
    spec.mkdir(parents=True)
    (spec / "cost.yaml").write_text("max_usd: 8\n")
    cap, blocking = C.load_cap("app1", strict=False, root=tmp_path)
    assert cap == 8.0 and blocking is True


# ---- cost_verify (pass / over-blocking / over-advisory / skip) ------------------

def test_cost_verify_blocking_pass_within_budget(tmp_path, monkeypatch):
    spec = tmp_path / "specs" / "app1"; spec.mkdir(parents=True)
    (spec / "cost.yaml").write_text("max_usd: 10\n")
    monkeypatch.setattr(C, "build_cost", lambda **k: 4.0)
    assert C.cost_verify("app1", root=tmp_path) is True


def test_cost_verify_blocking_fails_over_budget(tmp_path, monkeypatch):
    spec = tmp_path / "specs" / "app1"; spec.mkdir(parents=True)
    (spec / "cost.yaml").write_text("max_usd: 3\n")
    monkeypatch.setattr(C, "build_cost", lambda **k: 7.5)
    assert C.cost_verify("app1", root=tmp_path) is False


def test_cost_verify_advisory_passes_despite_breach(tmp_path, monkeypatch):
    # no cost.yaml → default ceiling → advisory
    monkeypatch.setattr(C, "build_cost", lambda **k: C.DEFAULT_MAX_USD + 100)
    assert C.cost_verify("app1", root=tmp_path) is True


def test_cost_verify_strict_makes_default_breach_block(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "build_cost", lambda **k: C.DEFAULT_MAX_USD + 100)
    assert C.cost_verify("app1", strict=True, root=tmp_path) is False


def test_cost_verify_override_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "build_cost", lambda **k: 6.0)
    assert C.cost_verify("app1", override=5.0, root=tmp_path) is False


def test_cost_verify_no_cost_is_skip_not_fail(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "build_cost", lambda **k: 0.0)
    # strict + would-be-blocking, but nothing to measure → skip (True)
    assert C.cost_verify("app1", strict=True, root=tmp_path) is True


# ---- gate dispatch --------------------------------------------------------------

def test_run_gate_dispatches_cost(monkeypatch):
    import area.verify as V
    seen = {}
    monkeypatch.setattr(V, "cost_verify",
                        lambda name, **kw: seen.update(name=name, **kw) or True)
    args = SimpleNamespace(backend="acp", model=None, strict=True,
                           cost_max=9.0, _build_start=123.0)
    assert CLI._run_gate("cost", "app1", args) is True
    assert seen["name"] == "app1" and seen["strict"] is True
    assert seen["override"] == 9.0 and seen["since"] == 123.0
