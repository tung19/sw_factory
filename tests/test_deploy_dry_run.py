"""`area deploy --dry-run`: print the deploy PLAN (provider, provenance verdict, the
PRODUCTION datastores it would create/migrate, the human-gate prompt) and change
NOTHING — no CF hardening, no provisioning, no confirm prompt, no deploy. This is
pstack's "side-effecting ops need --dry-run"; it doubles as a pre-flight a spec-engine
CI can read. Pure logic — no agents.

The verdict a dry run prints MUST match what a real deploy would do, so both paths go
through the one shared `_provenance_gate`; these tests pin that they agree.
"""
import area.build.cf_scaffold as S
import area.deploy as D
import area.deploy.cloudflare as C
import area.deploy.vercel as V
import area.provenance as P


def _app(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts":{"build":"next build"}}')
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "page.tsx").write_text("export default () => <div>hi</div>;")
    return tmp_path


def _boom_confirm(_desc):
    raise AssertionError("--dry-run must NOT prompt the human gate")


def _spy_deploy(called):
    def _d(_app_dir):
        called.append("deployed")
        return (True, "", "https://x.vercel.app")
    return _d


def test_dry_run_ok_provenance_would_proceed_but_deploys_nothing(monkeypatch, tmp_path):
    _app(tmp_path)
    P.write_provenance(tmp_path, name="a", target="plain", gates={"audit": True})
    called: list[str] = []
    monkeypatch.setattr(V, "deploy", _spy_deploy(called))
    ok, url = D.deploy_with_gate(tmp_path, confirm=_boom_confirm,
                                 require_provenance=True, dry_run=True)
    assert ok is True and url is None     # the plan WOULD proceed
    assert called == []                   # but nothing was deployed


def test_dry_run_absent_provenance_would_refuse(monkeypatch, tmp_path):
    _app(tmp_path)  # no provenance written
    called: list[str] = []
    monkeypatch.setattr(V, "deploy", _spy_deploy(called))
    ok, url = D.deploy_with_gate(tmp_path, confirm=_boom_confirm, dry_run=True)
    assert ok is False and url is None    # absent + required-by-default → would refuse
    assert called == []


def test_dry_run_mismatch_would_refuse(monkeypatch, tmp_path):
    _app(tmp_path)
    P.write_provenance(tmp_path, name="a", target="plain", gates={"audit": True})
    (tmp_path / "app" / "page.tsx").write_text("export default () => <div>HACKED</div>;")
    called: list[str] = []
    monkeypatch.setattr(V, "deploy", _spy_deploy(called))
    ok, _ = D.deploy_with_gate(tmp_path, confirm=_boom_confirm, dry_run=True,
                               require_provenance=True)
    assert ok is False and called == []


def test_dry_run_does_not_harden_or_deploy_a_cloudflare_app(monkeypatch, tmp_path):
    """The real CF path runs harden_cf_app (which MUTATES) before attesting; a dry run
    must never reach it, nor the deploy."""
    (tmp_path / "cloudflare.config.ts").write_text("export default {};")
    (tmp_path / "package.json").write_text('{"scripts":{"build:cf":"vite build"}}')
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "page.tsx").write_text("x")
    P.write_provenance(tmp_path, name="a", target="cloudflare", gates={"audit": True})
    monkeypatch.setattr(S, "harden_cf_app",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("dry-run must not harden/mutate the app")))
    monkeypatch.setattr(C, "deploy",
                        lambda a: (_ for _ in ()).throw(
                            AssertionError("dry-run must not deploy")))
    monkeypatch.setattr(C, "needs_d1", lambda a: True)   # the plan should still name D1
    ok, url = D.deploy_with_gate(tmp_path, confirm=_boom_confirm, dry_run=True,
                                 provider="cloudflare", require_provenance=True)
    assert ok is True and url is None


def test_cli_deploy_exposes_dry_run():
    from area.cli import _build_parser

    ns = _build_parser().parse_args(["deploy", "myapp", "--dry-run"])
    assert ns.dry_run is True
