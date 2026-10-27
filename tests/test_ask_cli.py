"""Audit fix [MED, F1/F2]: the three `claude -p` reviewer/intake paths now route
through the single engine seam (area.engine.ask_cli) — so they log to obs and
honor --model — and the OpenHands SDK import is behind mcp_stdio_server."""
import pytest

import area.engine as E
import area.engine.adapter as A
import area.obs
import area.spec.review as RV


class _Proc:
    def __init__(self, rc=0, out="hi", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def test_ask_cli_passes_model_and_logs_to_obs(monkeypatch):
    seen = {}
    monkeypatch.setattr(A.subprocess, "run",
                        lambda cmd, **k: (seen.__setitem__("cmd", cmd), _Proc())[1])
    logged = {}
    monkeypatch.setattr(area.obs, "log_run",
                        lambda label, **k: logged.update(label=label, **k))
    out = A.ask_cli("the prompt", model="claude-x", label="spec-review")
    assert out == "hi"
    assert "--model" in seen["cmd"] and "claude-x" in seen["cmd"]
    assert seen["cmd"][-1] == "the prompt"
    assert logged["label"] == "spec-review" and logged["backend"] == "claude-cli"
    assert logged["passed"] is True


def test_ask_cli_raises_on_nonzero_exit_and_still_logs(monkeypatch):
    monkeypatch.setattr(A.subprocess, "run", lambda cmd, **k: _Proc(rc=1, out="", err="boom"))
    logged = {}
    monkeypatch.setattr(area.obs, "log_run", lambda label, **k: logged.update(label=label, **k))
    with pytest.raises(RuntimeError):
        A.ask_cli("p", label="product")
    assert logged["passed"] is False          # logged even on failure (finally)


def test_ask_cli_omits_model_flag_when_none(monkeypatch):
    seen = {}
    monkeypatch.setattr(A.subprocess, "run", lambda cmd, **k: (seen.__setitem__("cmd", cmd), _Proc())[1])
    monkeypatch.setattr(area.obs, "log_run", lambda *a, **k: None)
    A.ask_cli("p")
    assert "--model" not in seen["cmd"]


def test_review_spec_default_path_threads_model_through_the_seam(tmp_path, monkeypatch):
    (tmp_path / "spec.yaml").write_text("name: x")
    (tmp_path / "acceptance.yaml").write_text("criteria: []")
    seen = {}
    monkeypatch.setattr(RV, "ask_cli", lambda p, **k: seen.update(k) or "assumptions: []")
    RV.review_spec("a real requirement", tmp_path, model="claude-z")
    assert seen.get("model") == "claude-z" and seen.get("label") == "spec-review"


def test_seam_exports_ask_cli_and_mcp_factory():
    assert hasattr(E, "ask_cli") and hasattr(E, "mcp_stdio_server")
