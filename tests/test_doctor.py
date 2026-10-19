"""area doctor: local-setup checks for the local-first workflow. Pure logic —
subprocess/which calls are stubbed."""
import area.doctor as D


def test_report_shape():
    rows = D.report()
    assert len(rows) == 6
    for name, status, detail, fix in rows:
        assert isinstance(name, str) and status in ("ok", "warn", "fail")
        assert isinstance(detail, str) and isinstance(fix, str)


def test_python_ok_on_current_interpreter():
    name, status, detail, fix = D.check_python()
    assert status == "ok"  # the suite itself runs on 3.12+


def test_node_present(monkeypatch):
    monkeypatch.setattr(D, "_ver", lambda cmd: "v20.0.0" if cmd[0] == "node" else None)
    name, status, detail, _ = D.check_node()
    assert status == "ok" and "v20" in detail


def test_node_missing(monkeypatch):
    monkeypatch.setattr(D, "_ver", lambda cmd: None)
    name, status, detail, fix = D.check_node()
    assert status == "fail" and fix


def test_git_present(monkeypatch):
    monkeypatch.setattr(D, "_which", lambda c: c == "git")
    monkeypatch.setattr(D, "_ver", lambda cmd: "git version 2.40")
    assert D.check_git()[1] == "ok"


def test_gh_missing_is_warn_not_fail(monkeypatch):
    monkeypatch.setattr(D, "_which", lambda c: False)
    assert D.check_gh()[1] == "warn"


def test_llm_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    assert D.check_llm()[1] == "ok"


def test_llm_claude_code(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(D, "_which", lambda c: c == "claude")
    name, status, detail, _ = D.check_llm()
    assert status == "ok" and "Claude Code" in detail


def test_llm_none_is_warn(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(D, "_which", lambda c: False)
    assert D.check_llm()[1] == "warn"


def test_deploy_creds_optional(monkeypatch):
    monkeypatch.delenv("VERCEL_TOKEN", raising=False)
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    monkeypatch.setattr(D, "_which", lambda c: False)
    assert D.check_deploy()[1] == "warn"
    monkeypatch.setenv("VERCEL_TOKEN", "x")
    assert D.check_deploy()[1] == "ok"
