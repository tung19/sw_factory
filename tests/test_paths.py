"""area.paths — single source for REPO/WORKSPACE with an AREA_WORKSPACE override,
so generated apps can live OUTSIDE the factory checkout (isolation + F3 fix)."""
from pathlib import Path

import area.paths as P


def test_workspace_defaults_inside_repo(monkeypatch):
    monkeypatch.delenv("AREA_WORKSPACE", raising=False)
    assert P.workspace() == P.REPO / "workspace"


def test_workspace_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("AREA_WORKSPACE", str(tmp_path))
    assert P.workspace() == tmp_path.resolve()


def test_workspace_expands_user(monkeypatch):
    monkeypatch.setenv("AREA_WORKSPACE", "~/area-generated-x")
    assert P.workspace() == (Path.home() / "area-generated-x").resolve()


def test_blank_env_falls_back_to_repo(monkeypatch):
    monkeypatch.setenv("AREA_WORKSPACE", "   ")
    assert P.workspace() == P.REPO / "workspace"
