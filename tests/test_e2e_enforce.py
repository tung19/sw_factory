"""Audit fix [MED, F13/F14]: the e2e gate is FORCED before deploying an
auth/session/form app (logic-green ≠ live-works — a holdout passed while live
signup was broken). Recommended-only when not deploying; --no-e2e overrides."""
from types import SimpleNamespace

import area.cli as CLI


def test_looks_auth_detects_and_ignores(tmp_path):
    (tmp_path / "spec.yaml").write_text("features:\n  - login with password")
    assert CLI._looks_auth(tmp_path) is True
    d2 = tmp_path / "plain"; d2.mkdir()
    (d2 / "spec.yaml").write_text("features:\n  - add two numbers, show the sum")
    assert CLI._looks_auth(d2) is False


def _run(monkeypatch, tmp_path, *, spec: str, argv: list[str]):
    """Drive `area run` with a mocked pipeline + gates, returning the gates run."""
    sd = tmp_path / "specs" / "t"; sd.mkdir(parents=True)
    (sd / "spec.yaml").write_text(spec)
    res = SimpleNamespace(clarify_needed=False, passed=True, name="t",
                          spec_dir=sd, app_dir=tmp_path / "apps" / "t")
    (tmp_path / "apps" / "t").mkdir(parents=True)
    import area.deploy
    import area.pipeline
    monkeypatch.setattr(area.pipeline, "WORKSPACE", tmp_path)
    monkeypatch.setattr(area.pipeline, "run_pipeline", lambda req, **kw: res)
    ran: list[str] = []
    monkeypatch.setattr(CLI, "_run_gate", lambda g, n, a: (ran.append(g), True)[1])
    monkeypatch.setattr(area.deploy, "deploy_with_gate", lambda *a, **k: (True, None))
    CLI.main(["run", "x", "--name", "t", *argv])
    return ran


AUTH = "features:\n  - signup and login; passwords hashed; session cookie"
PLAIN = "features:\n  - tip calculator: compute tip and total"


def test_e2e_forced_before_deploy_for_auth_app(monkeypatch, tmp_path):
    ran = _run(monkeypatch, tmp_path, spec=AUTH, argv=["--deploy", "--yes"])
    assert "e2e" in ran


def test_e2e_not_forced_for_plain_app_on_deploy(monkeypatch, tmp_path):
    ran = _run(monkeypatch, tmp_path, spec=PLAIN, argv=["--deploy", "--yes"])
    assert "e2e" not in ran


def test_no_e2e_flag_overrides_the_force(monkeypatch, tmp_path):
    ran = _run(monkeypatch, tmp_path, spec=AUTH, argv=["--deploy", "--yes", "--no-e2e"])
    assert "e2e" not in ran


def test_auth_without_deploy_only_recommends(monkeypatch, tmp_path):
    ran = _run(monkeypatch, tmp_path, spec=AUTH, argv=["--no-open"])
    assert "e2e" not in ran        # recommended, not forced, when not deploying
