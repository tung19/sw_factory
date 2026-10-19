"""Multi-provider deploy: auto-detect cloudflare vs vercel, dispatch correctly,
and the Vercel deploy command. The actual CLI calls need live auth, not run here."""
import area.deploy as D
import area.deploy.cloudflare as C
import area.deploy.vercel as V


def test_detect_cloudflare_by_config(tmp_path):
    (tmp_path / "cloudflare.config.ts").write_text("export default {}")
    assert D.detect_provider(tmp_path) == "cloudflare"


def test_detect_cloudflare_by_build_cf(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts":{"build:cf":"vite build"}}')
    assert D.detect_provider(tmp_path) == "cloudflare"


def test_detect_vercel_for_vanilla_next(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts":{"build":"next build"}}')
    assert D.detect_provider(tmp_path) == "vercel"


def test_detect_vercel_when_empty(tmp_path):
    assert D.detect_provider(tmp_path) == "vercel"


def test_gate_routes_to_vercel(monkeypatch, tmp_path):
    (tmp_path / "package.json").write_text('{"scripts":{"build":"next build"}}')
    called = []
    monkeypatch.setattr(V, "deploy",
                        lambda a: (called.append("vercel"), (True, "o", "https://x.vercel.app"))[1])
    monkeypatch.setattr(C, "deploy",
                        lambda a: (called.append("cf"), (True, "", "https://x.workers.dev"))[1])
    ok, url = D.deploy_with_gate(tmp_path, confirm=lambda p: True)
    assert ok and called == ["vercel"] and url == "https://x.vercel.app"


def test_gate_routes_to_cloudflare_and_provisions_d1(monkeypatch, tmp_path):
    (tmp_path / "cloudflare.config.ts").write_text("env: { DB: bindings.d1() }")
    order = []
    monkeypatch.setattr(C, "provision_d1", lambda a: (order.append("provision"), (True, "ok"))[1])
    monkeypatch.setattr(C, "deploy",
                        lambda a: (order.append("cf-deploy"), (True, "", "https://x.workers.dev"))[1])
    monkeypatch.setattr(V, "deploy", lambda a: (order.append("vercel"), (True, "", None))[1])
    D.deploy_with_gate(tmp_path, confirm=lambda p: True)
    assert order == ["provision", "cf-deploy"]


def test_gate_explicit_provider_overrides_detection(monkeypatch, tmp_path):
    (tmp_path / "cloudflare.config.ts").write_text("x")  # would detect cloudflare
    called = []
    monkeypatch.setattr(V, "deploy", lambda a: (called.append("vercel"), (True, "", None))[1])
    monkeypatch.setattr(C, "deploy", lambda a: (called.append("cf"), (True, "", None))[1])
    D.deploy_with_gate(tmp_path, confirm=lambda p: True, provider="vercel")
    assert called == ["vercel"]


def test_gate_cancelled_deploys_nothing(monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr(V, "deploy", lambda a: (called.append("v"), (True, "", None))[1])
    ok, _ = D.deploy_with_gate(tmp_path, confirm=lambda p: False)
    assert not ok and called == []


def test_vercel_deploy_command(monkeypatch, tmp_path):
    cap = {}

    def fake_run(cmd, **kw):
        cap["cmd"] = cmd

        class R:
            returncode = 0
            stdout = "Production: https://myapp.vercel.app [2s]"
            stderr = ""
        return R()

    monkeypatch.setattr(V.subprocess, "run", fake_run)
    ok, out, url = V.deploy(tmp_path)
    assert ok and url == "https://myapp.vercel.app"
    assert "vercel deploy --prod" in cap["cmd"][-1]
