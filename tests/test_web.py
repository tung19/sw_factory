"""Dashboard backend: job command assembly (intake/tdd/gates) + requirement-doc
upload parsing (PDF/Word/Markdown). UI is served HTML; these cover the logic."""
import io
from pathlib import Path

import pytest

import area.web.jobs as J
import area.web.upload as U


# ---- job command assembly ----------------------------------------------------

def test_cmd_run_with_tdd_all_deploy():
    cmd = J.MANAGER._cmd("run", {
        "requirement": "do x", "name": "app", "target": "plain",
        "tdd": True, "all": True, "deploy": True,
    })
    assert cmd[1] == "run" and "do x" in cmd
    assert "--tdd" in cmd and "--all" in cmd
    assert "--deploy" in cmd and "--yes" in cmd
    assert cmd[cmd.index("--target") + 1] == "plain"


def test_cmd_intake_tdd():
    cmd = J.MANAGER._cmd("intake", {
        "artifacts": "/tmp/aidlc", "name": "i", "target": "cloudflare", "tdd": True,
    })
    assert cmd[1] == "intake" and "/tmp/aidlc" in cmd and "--tdd" in cmd


def test_cmd_clone_individual_gates_no_all():
    cmd = J.MANAGER._cmd("clone", {
        "source": "/repo", "name": "c", "srcKind": "path",
        "audit": True, "e2e": True,
    })
    assert cmd[1] == "clone" and cmd[cmd.index("--kind") + 1] == "path"
    assert "--audit" in cmd and "--e2e" in cmd
    assert "--all" not in cmd and "--tdd" not in cmd and "--chaos" not in cmd


def test_cmd_unknown_raises():
    with pytest.raises(ValueError):
        J.MANAGER._cmd("bogus", {"name": "x"})


def test_flags_empty_when_nothing_set():
    assert J.JobManager._flags({}) == []


# ---- requirement-document upload parsing ------------------------------------

def test_parse_text_formats():
    assert "hello world" in U.parse_file("a.md", b"hello world")
    assert U.parse_file("a.txt", b"plain") == "plain"


def test_parse_docx():
    import docx

    d = docx.Document()
    d.add_paragraph("Requirement: user can add a todo")
    buf = io.BytesIO()
    d.save(buf)
    assert "add a todo" in U.parse_file("req.docx", buf.getvalue())


def test_parse_pdf_bad_bytes_is_graceful():
    out = U.parse_file("x.pdf", b"not really a pdf")
    assert isinstance(out, str)  # graceful message, never raises


def test_save_intake_builds_artifact_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(U, "UPLOAD_DIR", tmp_path)
    res = U.save_intake(
        "MyApp!", [("req.md", b"# Req\nadd a todo")], description="also: dark mode"
    )
    d = Path(res["dir"])
    assert d.exists() and d.name == "MyApp"            # name sanitized to one segment
    assert res["chars"] > 0
    assert "add a todo" in res["text"] and "dark mode" in res["text"]
    assert "_description.md" in res["files"]
    assert any(f.endswith(".md") and f != "_description.md" for f in res["files"])


def test_save_intake_description_only(monkeypatch, tmp_path):
    monkeypatch.setattr(U, "UPLOAD_DIR", tmp_path)
    res = U.save_intake("x", [], description="just a short idea")
    assert "just a short idea" in res["text"] and res["files"] == ["_description.md"]
