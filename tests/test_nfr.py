"""area.verify.nfr — the deterministic perf/NFR budget gate. Pure measurement +
evaluation + budget sourcing + gate dispatch; no agent, no live build (same
posture as test_deploy_d1: the subprocess build path isn't run here)."""
from types import SimpleNamespace

import area.cli as CLI
import area.verify.nfr as N


# ---- parse_budget_yaml ----------------------------------------------------------

def test_parse_budget_yaml_numbers_comments_floats():
    text = "# budget\nbundle_kib: 2048  # 2 MiB\n\ndep_count: 25\nbad: abc\np95_ms: 1.5\n"
    assert N.parse_budget_yaml(text) == {"bundle_kib": 2048, "dep_count": 25, "p95_ms": 1.5}


# ---- evaluate -------------------------------------------------------------------

def test_evaluate_within_over_equal_and_only_shared_keys():
    metrics = {"bundle_kib": 100, "dep_count": 40, "untracked": 9}
    budget = {"bundle_kib": 150, "dep_count": 40, "build_ms": 1000}  # build_ms not measured
    res = {r["metric"]: r for r in N.evaluate(metrics, budget)}
    assert res["bundle_kib"]["ok"] is True          # 100 <= 150
    assert res["dep_count"]["ok"] is True            # 40 <= 40 (equal passes)
    assert "build_ms" not in res                     # budgeted but not measured → skipped
    assert "untracked" not in res                    # measured but not budgeted → skipped


def test_evaluate_flags_a_breach():
    res = N.evaluate({"bundle_kib": 200}, {"bundle_kib": 150})
    assert res[0]["ok"] is False and res[0]["value"] == 200 and res[0]["limit"] == 150


# ---- load_budget ----------------------------------------------------------------

def test_load_budget_defaults_are_advisory(tmp_path):
    budget, blocking = N.load_budget("app1", root=tmp_path)
    assert blocking is False and budget == N.DEFAULT_BUDGET


def test_load_budget_strict_blocks_even_without_file(tmp_path):
    _, blocking = N.load_budget("app1", strict=True, root=tmp_path)
    assert blocking is True


def test_load_budget_user_yaml_blocks_and_overrides(tmp_path):
    spec = tmp_path / "specs" / "app1"
    spec.mkdir(parents=True)
    (spec / "nfr.yaml").write_text("bundle_kib: 2048\n")
    budget, blocking = N.load_budget("app1", root=tmp_path)
    assert blocking is True
    assert budget["bundle_kib"] == 2048           # overridden
    assert budget["dep_count"] == N.DEFAULT_BUDGET["dep_count"]  # default kept


# ---- measure (no build) ---------------------------------------------------------

def _fake_app(tmp_path, *, bundle_bytes=2048, deps=("next", "react", "zod")):
    app = tmp_path / "apps" / "app1"
    (app / ".next" / "static").mkdir(parents=True)
    (app / ".next" / "static" / "app.js").write_bytes(b"x" * bundle_bytes)
    (app / ".next" / "cache").mkdir()
    (app / ".next" / "cache" / "junk.bin").write_bytes(b"y" * (10 * 1024 * 1024))  # must be EXCLUDED
    (app / "package.json").write_text(
        '{"dependencies":{' + ",".join(f'"{d}":"1"' for d in deps) + "}}"
    )
    return app


def test_measure_counts_bundle_deps_excludes_cache(tmp_path):
    _fake_app(tmp_path, bundle_bytes=2048)
    m = N.measure(tmp_path / "apps" / "app1", run_build=False)
    assert m["bundle_kib"] == 2            # 2048 bytes; the 10 MiB cache file excluded
    assert m["dep_count"] == 3
    assert "build_ms" not in m             # not run_build


# ---- nfr_verify (advisory vs blocking) ------------------------------------------

def test_nfr_verify_blocking_pass_within_budget(tmp_path):
    _fake_app(tmp_path)
    spec = tmp_path / "specs" / "app1"; spec.mkdir(parents=True)
    (spec / "nfr.yaml").write_text("bundle_kib: 100\n")
    assert N.nfr_verify("app1", root=tmp_path) is True


def test_nfr_verify_blocking_fails_over_budget(tmp_path):
    _fake_app(tmp_path)
    spec = tmp_path / "specs" / "app1"; spec.mkdir(parents=True)
    (spec / "nfr.yaml").write_text("bundle_kib: 1\n")   # 2 KiB > 1 KiB
    assert N.nfr_verify("app1", root=tmp_path) is False


def test_nfr_verify_advisory_passes_despite_breach(tmp_path, monkeypatch):
    _fake_app(tmp_path)
    monkeypatch.setattr(N, "measure", lambda app, **k: {"bundle_kib": 99999})  # way over default
    assert N.nfr_verify("app1", root=tmp_path) is True   # advisory → non-fatal


def test_nfr_verify_no_metrics_is_skip(tmp_path):
    (tmp_path / "apps" / "app1").mkdir(parents=True)     # empty app, no build output
    assert N.nfr_verify("app1", root=tmp_path) is True


# ---- gate dispatch --------------------------------------------------------------

def test_run_gate_dispatches_nfr(monkeypatch):
    import area.verify as V
    seen = {}
    monkeypatch.setattr(V, "nfr_verify",
                        lambda name, **kw: seen.update(name=name, **kw) or True)
    args = SimpleNamespace(backend="acp", model=None, strict=True, nfr_build=True)
    assert CLI._run_gate("nfr", "app1", args) is True
    assert seen["name"] == "app1" and seen["strict"] is True and seen["run_build"] is True
