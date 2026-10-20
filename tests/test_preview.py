"""Auto-open-the-app-in-a-browser preview after a green build.

Injected seams (opener/spawn/is_ready) keep it agent-free + headless; a fake app dir
(no package.json) is always a no-op, which is why every other main()-driven test stays
safe without stubbing anything."""
import types

import area.cli
import area.pipeline
import area.preview as PV


def test_has_runnable_app(tmp_path):
    assert PV._has_runnable_app(tmp_path) is False
    (tmp_path / "package.json").write_text('{"scripts": {"dev": "next dev"}}')
    assert PV._has_runnable_app(tmp_path) is True
    (tmp_path / "package.json").write_text('{"scripts": {"build": "x"}}')
    assert PV._has_runnable_app(tmp_path) is False  # needs dev or start


def test_preview_disabled():
    assert PV.open_preview("/x", want_open=False)["opened"] is False


def test_preview_env_off(monkeypatch, tmp_path):
    monkeypatch.setenv("AREA_NO_PREVIEW", "1")
    assert PV.open_preview(tmp_path)["opened"] is False


def test_preview_opens_deployed_url():
    seen = []
    r = PV.open_preview("/x", deployed_url="https://app.example.dev", opener=seen.append)
    assert r["opened"] and r["url"] == "https://app.example.dev" and r["server"] is False
    assert seen == ["https://app.example.dev"]


def test_preview_no_runnable_app(tmp_path):
    r = PV.open_preview(tmp_path)  # no package.json → never spawns a server
    assert r["opened"] is False and "no runnable" in r["reason"]


def test_preview_local_starts_server_and_opens(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts": {"dev": "next dev"}}')
    opened, spawned = [], []

    def spawn():
        spawned.append(1)
        return types.SimpleNamespace(pid=4321)

    r = PV.open_preview(tmp_path, opener=opened.append, spawn=spawn, is_ready=lambda: True)
    assert r["opened"] and r["server"] and r["pid"] == 4321
    assert spawned == [1]
    assert opened and opened[0].startswith("http://127.0.0.1:")


# ---------- CLI wiring: --open default on, --no-open skips ----------
def _res(tmp_path):
    return types.SimpleNamespace(passed=True, name="app", spec_dir=tmp_path, app_dir=tmp_path)


def test_cli_open_default_calls_preview(monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr(area.pipeline, "run_pipeline", lambda req, **kw: _res(tmp_path))
    monkeypatch.setattr(area.preview, "open_preview",
                        lambda app_dir, **kw: called.append(app_dir) or {"opened": True})
    area.cli.main(["run", "x", "--name", "t"])
    assert called  # default --open fired


def test_cli_no_open_skips_preview(monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr(area.pipeline, "run_pipeline", lambda req, **kw: _res(tmp_path))
    monkeypatch.setattr(area.preview, "open_preview",
                        lambda app_dir, **kw: called.append(app_dir) or {"opened": True})
    area.cli.main(["run", "x", "--name", "t", "--no-open"])
    assert not called
