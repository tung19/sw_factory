"""CLI product-name resolution + collision guard: every product gets its own
workspace/apps/<name>, so a name is required (prompted interactively, errored
non-interactively) and an existing product folder is never silently clobbered."""
import builtins

import pytest

import area.cli as CLI


# ---- _slug_from -----------------------------------------------------------------

def test_slug_from_requirement():
    assert CLI._slug_from("A multi-page Team Task Board!", "app") == "a-multi-page-team"
    assert CLI._slug_from("", "app") == "app"            # empty → fallback
    assert CLI._slug_from("!!! ??? ...", "clone") == "clone"  # no word chars → fallback


# ---- _resolve_name --------------------------------------------------------------

def test_resolve_name_uses_explicit_and_sanitizes():
    assert CLI._resolve_name("My App", hint="x", fallback="app") == CLI.safe_name("My App")


def test_resolve_name_prompts_when_interactive(monkeypatch):
    monkeypatch.setattr(CLI.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(builtins, "input", lambda *_: "chosen-name")
    assert CLI._resolve_name(None, hint="a todo app", fallback="app") == "chosen-name"


def test_resolve_name_interactive_empty_takes_suggestion(monkeypatch):
    monkeypatch.setattr(CLI.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(builtins, "input", lambda *_: "")   # accept the suggestion
    assert CLI._resolve_name(None, hint="Team Task Board", fallback="app") == "team-task-board"


def test_resolve_name_noninteractive_without_name_errors(monkeypatch):
    monkeypatch.setattr(CLI.sys.stdin, "isatty", lambda: False)
    with pytest.raises(SystemExit) as e:
        CLI._resolve_name(None, hint="a todo app", fallback="app")
    assert e.value.code == 2


# ---- _check_collision -----------------------------------------------------------

def _mk_app(ws, name):
    d = ws / "apps" / name
    d.mkdir(parents=True)
    (d / "package.json").write_text("{}")
    return d


def test_collision_free_name_passes_through(tmp_path, monkeypatch):
    monkeypatch.setattr("area.pipeline.WORKSPACE", tmp_path)
    assert CLI._check_collision("fresh") == "fresh"


def test_collision_noninteractive_warns_and_proceeds(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("area.pipeline.WORKSPACE", tmp_path)
    _mk_app(tmp_path, "taken")
    monkeypatch.setattr(CLI.sys.stdin, "isatty", lambda: False)
    assert CLI._check_collision("taken") == "taken"       # proceeds (overwrite)
    assert "đã tồn tại" in capsys.readouterr().out


def test_collision_interactive_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr("area.pipeline.WORKSPACE", tmp_path)
    _mk_app(tmp_path, "taken")
    monkeypatch.setattr(CLI.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(builtins, "input", lambda *_: "o")
    assert CLI._check_collision("taken") == "taken"


def test_collision_interactive_new_name(tmp_path, monkeypatch):
    monkeypatch.setattr("area.pipeline.WORKSPACE", tmp_path)
    _mk_app(tmp_path, "taken")
    monkeypatch.setattr(CLI.sys.stdin, "isatty", lambda: True)
    answers = iter(["", "taken-v2"])  # [Enter]=rename, then the new name (free)
    monkeypatch.setattr(builtins, "input", lambda *_: next(answers))
    assert CLI._check_collision("taken") == "taken-v2"


def test_collision_interactive_iterate_bails(tmp_path, monkeypatch):
    monkeypatch.setattr("area.pipeline.WORKSPACE", tmp_path)
    _mk_app(tmp_path, "taken")
    monkeypatch.setattr(CLI.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(builtins, "input", lambda *_: "i")
    with pytest.raises(SystemExit) as e:
        CLI._check_collision("taken")
    assert e.value.code == 0
