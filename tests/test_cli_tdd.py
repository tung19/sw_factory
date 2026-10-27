"""CLI wiring: --tdd is accepted and threaded into the pipeline, and it makes
the post-build 'verify' gate redundant (so it is skipped)."""
import types

import area.cli
import area.pipeline


def _res(tmp_path):
    return types.SimpleNamespace(
        passed=True, name="app", spec_dir=tmp_path, app_dir=tmp_path
    )


def test_run_threads_tdd_true(monkeypatch, tmp_path):
    cap = {}

    def fake(req, **kw):
        cap.update(kw, req=req)
        return _res(tmp_path)

    monkeypatch.setattr(area.pipeline, "run_pipeline", fake)
    assert area.cli.main(["run", "build a todo", "--name", "todo", "--tdd", "--target", "plain"]) == 0
    assert cap["tdd"] is True and cap["req"] == "build a todo"


def test_run_tdd_defaults_false(monkeypatch, tmp_path):
    cap = {}
    monkeypatch.setattr(
        area.pipeline, "run_pipeline",
        lambda req, **kw: (cap.update(kw), _res(tmp_path))[1],
    )
    area.cli.main(["run", "x", "--name", "t"])
    assert cap["tdd"] is False


def test_clone_threads_tdd_true(monkeypatch, tmp_path):
    cap = {}

    def fake(src, **kw):
        cap.update(kw, src=src)
        return _res(tmp_path)

    monkeypatch.setattr(area.pipeline, "clone_pipeline", fake)
    assert area.cli.main(["clone", "/some/path", "--name", "cl", "--tdd"]) == 0
    assert cap["tdd"] is True


def test_tdd_skips_redundant_verify_gate(monkeypatch, tmp_path):
    ran = []
    monkeypatch.setattr(area.pipeline, "run_pipeline", lambda req, **kw: _res(tmp_path))
    monkeypatch.setattr(area.cli, "_run_gate", lambda g, n, a: (ran.append(g), True)[1])
    assert area.cli.main(["run", "x", "--name", "t", "--tdd", "--all"]) == 0
    # derive from the registry (the single source) so adding a gate can't drift this
    assert "verify" not in ran
    assert set(ran) == set(area.cli._GATE_ORDER) - {"verify"}


def test_non_tdd_runs_verify_gate(monkeypatch, tmp_path):
    ran = []
    monkeypatch.setattr(area.pipeline, "run_pipeline", lambda req, **kw: _res(tmp_path))
    monkeypatch.setattr(area.cli, "_run_gate", lambda g, n, a: (ran.append(g), True)[1])
    area.cli.main(["run", "x", "--name", "t", "--all"])
    assert "verify" in ran
