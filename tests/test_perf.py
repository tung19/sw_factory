"""area.verify.perf — the live perf/load budget gate. Pure percentile/evaluate/
budget logic + gate dispatch + verdict posture. The real server boot + load fire
is NOT exercised here (same posture as test_nfr/test_deploy_d1: the subprocess
path isn't run in unit tests); `measure` is monkeypatched for the verdict tests."""
from types import SimpleNamespace

import area.cli as CLI
import area.verify.perf as P


# ---- percentile -----------------------------------------------------------------

def test_percentile_nearest_rank_and_edges():
    xs = [10.0, 20.0, 30.0, 40.0, 100.0]
    assert P.percentile(xs, 50) == 30.0      # median
    assert P.percentile(xs, 95) == 100.0     # tail → max
    assert P.percentile(xs, 99) == 100.0
    assert P.percentile([], 95) == 0.0       # empty → 0
    assert P.percentile([7.0], 50) == 7.0    # single sample


# ---- evaluate (direction-aware: ceilings vs the throughput floor) ---------------

def test_evaluate_ceiling_metrics():
    res = {r["metric"]: r for r in P.evaluate(
        {"p95_ms": 800, "error_rate_pct": 2}, {"p95_ms": 1000, "error_rate_pct": 1})}
    assert res["p95_ms"]["ok"] is True        # 800 <= 1000
    assert res["error_rate_pct"]["ok"] is False  # 2 > 1
    assert res["p95_ms"]["floor"] is False


def test_evaluate_throughput_is_a_floor():
    res = P.evaluate({"throughput_rps": 12}, {"throughput_rps": 20})
    assert res[0]["floor"] is True
    assert res[0]["ok"] is False              # 12 < 20 → under the floor → breach
    res2 = P.evaluate({"throughput_rps": 25}, {"throughput_rps": 20})
    assert res2[0]["ok"] is True              # 25 >= 20 → meets the floor


def test_evaluate_only_shared_keys():
    res = {r["metric"]: r for r in P.evaluate(
        {"p50_ms": 100, "untracked": 9}, {"p50_ms": 500, "p99_ms": 3000})}
    assert res["p50_ms"]["ok"] is True
    assert "p99_ms" not in res    # budgeted but not measured → skipped
    assert "untracked" not in res  # measured but not budgeted → skipped


# ---- load_budget ----------------------------------------------------------------

def test_load_budget_defaults_are_advisory(tmp_path):
    budget, blocking = P.load_budget("app1", root=tmp_path)
    assert blocking is False and budget == P.DEFAULT_BUDGET


def test_load_budget_strict_blocks_even_without_file(tmp_path):
    _, blocking = P.load_budget("app1", strict=True, root=tmp_path)
    assert blocking is True


def test_load_budget_user_yaml_blocks_and_overrides(tmp_path):
    spec = tmp_path / "specs" / "app1"
    spec.mkdir(parents=True)
    (spec / "perf.yaml").write_text("p95_ms: 800\nthroughput_rps: 20\n")
    budget, blocking = P.load_budget("app1", root=tmp_path)
    assert blocking is True
    assert budget["p95_ms"] == 800                      # overridden
    assert budget["throughput_rps"] == 20               # overridden
    assert budget["p50_ms"] == P.DEFAULT_BUDGET["p50_ms"]  # default kept


# ---- perf_verify (advisory vs blocking vs skip) ---------------------------------

def _app(tmp_path):
    app = tmp_path / "apps" / "app1"
    app.mkdir(parents=True)
    return app


def test_perf_verify_blocking_pass_within_budget(tmp_path, monkeypatch):
    _app(tmp_path)
    spec = tmp_path / "specs" / "app1"; spec.mkdir(parents=True)
    (spec / "perf.yaml").write_text("p95_ms: 1000\nthroughput_rps: 5\n")
    monkeypatch.setattr(P, "measure",
                        lambda app, **k: ({"p95_ms": 200, "throughput_rps": 50,
                                           "_server": "dev"}, None))
    assert P.perf_verify("app1", root=tmp_path) is True


def test_perf_verify_blocking_fails_on_latency_breach(tmp_path, monkeypatch):
    _app(tmp_path)
    spec = tmp_path / "specs" / "app1"; spec.mkdir(parents=True)
    (spec / "perf.yaml").write_text("p95_ms: 100\n")
    monkeypatch.setattr(P, "measure",
                        lambda app, **k: ({"p95_ms": 900, "_server": "dev"}, None))
    assert P.perf_verify("app1", root=tmp_path) is False


def test_perf_verify_blocking_fails_under_throughput_floor(tmp_path, monkeypatch):
    _app(tmp_path)
    spec = tmp_path / "specs" / "app1"; spec.mkdir(parents=True)
    (spec / "perf.yaml").write_text("throughput_rps: 100\n")
    monkeypatch.setattr(P, "measure",
                        lambda app, **k: ({"throughput_rps": 3, "_server": "dev"}, None))
    assert P.perf_verify("app1", root=tmp_path) is False   # 3 < 100 floor → breach


def test_perf_verify_advisory_passes_despite_breach(tmp_path, monkeypatch):
    _app(tmp_path)  # no perf.yaml → defaults → advisory
    monkeypatch.setattr(P, "measure",
                        lambda app, **k: ({"p95_ms": 99999, "_server": "dev"}, None))
    assert P.perf_verify("app1", root=tmp_path) is True     # advisory → non-fatal


def test_perf_verify_strict_makes_default_breach_block(tmp_path, monkeypatch):
    _app(tmp_path)
    monkeypatch.setattr(P, "measure",
                        lambda app, **k: ({"p95_ms": 99999, "_server": "dev"}, None))
    assert P.perf_verify("app1", strict=True, root=tmp_path) is False


def test_perf_verify_unmeasurable_is_skip_not_fail(tmp_path, monkeypatch):
    _app(tmp_path)
    monkeypatch.setattr(P, "measure", lambda app, **k: ({}, "app did not boot"))
    assert P.perf_verify("app1", root=tmp_path) is True     # cannot measure → skip


def test_perf_verify_missing_app_raises(tmp_path):
    try:
        P.perf_verify("nope", root=tmp_path)
    except RuntimeError as e:
        assert "no app" in str(e)
    else:
        raise AssertionError("expected RuntimeError for a missing app")


# ---- gate dispatch --------------------------------------------------------------

def test_run_gate_dispatches_perf(monkeypatch):
    import area.verify as V
    seen = {}
    monkeypatch.setattr(V, "perf_verify",
                        lambda name, **kw: seen.update(name=name, **kw) or True)
    args = SimpleNamespace(backend="acp", model=None, strict=True,
                           perf_requests=50, perf_concurrency=4)
    assert CLI._run_gate("perf", "app1", args) is True
    assert seen["name"] == "app1" and seen["strict"] is True
    assert seen["total"] == 50 and seen["concurrency"] == 4
