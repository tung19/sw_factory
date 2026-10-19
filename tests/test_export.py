"""`area export`: hand a generated app off as its OWN git repo. Pure parts
(.gitignore, source copy excluding deps/build, command assembly). The real git/gh
calls are stubbed — not run here."""
import subprocess
import types

import area.export as E


def _mk_app(tmp_path, name="myapp"):
    app = tmp_path / "apps" / name
    (app / "app").mkdir(parents=True)
    (app / "app" / "page.tsx").write_text("export default () => null;")
    (app / "package.json").write_text('{"name":"myapp"}')
    (app / "node_modules" / "dep").mkdir(parents=True)
    (app / "node_modules" / "dep" / "i.js").write_text("x")
    (app / ".next").mkdir()
    (app / ".next" / "o").write_text("y")
    return app


# ---- gitignore + copy -------------------------------------------------------

def test_ensure_gitignore_writes_then_skips(tmp_path):
    assert E.ensure_gitignore(tmp_path) is True
    assert (tmp_path / ".gitignore").exists()
    assert "node_modules/" in (tmp_path / ".gitignore").read_text()
    assert E.ensure_gitignore(tmp_path) is False  # already present


def test_copy_source_excludes_deps_and_build(tmp_path):
    app = _mk_app(tmp_path)
    dest = tmp_path / "out" / "myapp"
    E.copy_source(app, dest)
    assert (dest / "app" / "page.tsx").exists()
    assert (dest / "package.json").exists()
    assert not (dest / "node_modules").exists()   # deps excluded
    assert not (dest / ".next").exists()           # build output excluded


# ---- export_app wiring (git/gh stubbed) -------------------------------------

def _capture(monkeypatch):
    cmds = []

    def fake_run(cmd, cwd):
        cmds.append(cmd)
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(E, "_run", fake_run)
    return cmds


def test_export_in_place_inits_and_commits(monkeypatch, tmp_path):
    _mk_app(tmp_path)
    cmds = _capture(monkeypatch)
    ok, log = E.export_app("myapp", workspace=tmp_path)
    assert ok
    assert any("git init" in c for c in cmds)
    assert any("git add -A" in c for c in cmds)
    assert any("git -c user.name=AREA" in c and "commit" in c for c in cmds)
    assert "initial generated app" in log or ".gitignore" in log


def test_export_out_copies_before_init(monkeypatch, tmp_path):
    _mk_app(tmp_path)
    _capture(monkeypatch)
    ok, log = E.export_app("myapp", out=tmp_path / "exported", workspace=tmp_path)
    assert ok
    assert (tmp_path / "exported" / "myapp" / "package.json").exists()
    assert "copied source" in log


def test_export_sets_remote_and_pushes(monkeypatch, tmp_path):
    _mk_app(tmp_path)
    cmds = _capture(monkeypatch)
    E.export_app("myapp", repo="https://github.com/u/myapp.git", push=True, workspace=tmp_path)
    assert any("remote add origin https://github.com/u/myapp.git" in c for c in cmds)
    assert any("git push -u origin HEAD" in c for c in cmds)


def test_export_create_uses_gh(monkeypatch, tmp_path):
    _mk_app(tmp_path)
    cmds = _capture(monkeypatch)
    E.export_app("myapp", create=True, visibility="public", workspace=tmp_path)
    assert any("gh repo create myapp --public --source=." in c for c in cmds)


def test_export_custom_message(monkeypatch, tmp_path):
    _mk_app(tmp_path)
    cmds = _capture(monkeypatch)
    E.export_app("myapp", message="first cut", workspace=tmp_path)
    assert any("commit" in c and "first cut" in c for c in cmds)


def test_export_missing_app_raises(tmp_path):
    import pytest
    with pytest.raises(RuntimeError):
        E.export_app("nope", workspace=tmp_path)
