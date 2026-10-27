"""PR8 Phase 2 — the dashboard Inception wiring: the `inception` job command and
the read/save helpers that back the review-and-edit panel (the human shaping the
oracle before build). Pure/file-level; no server, no agent."""
import json

import area.web.jobs as J


def test_cmd_builds_inception_command():
    cmd = J.MANAGER._cmd("inception", {"requirement": "a todo app", "name": "todo",
                                       "target": "plain"})
    assert cmd[1] == "inception" and "a todo app" in cmd
    assert "--name" in cmd and "todo" in cmd
    assert "--yes" in cmd                       # dashboard gates AFTER, via review/edit
    assert cmd[cmd.index("--target") + 1] == "plain"


def test_read_inception_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(J, "WORKSPACE", tmp_path)
    out = J.read_inception("nope")
    assert out["files"] == {} and out["dir"].endswith("nope/inception")


def test_read_inception_reads_md_files(tmp_path, monkeypatch):
    monkeypatch.setattr(J, "WORKSPACE", tmp_path)
    d = tmp_path / "specs" / "app1" / "inception"
    d.mkdir(parents=True)
    (d / "01-intent.md").write_text("# Intent")
    (d / "aidlc_trace.jsonl").write_text('{"x":1}\n')   # not .md → ignored
    out = J.read_inception("app1")
    assert out["files"] == {"01-intent.md": "# Intent"}


def test_save_inception_writes_md_skips_traversal_and_emits_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(J, "WORKSPACE", tmp_path)
    res = J.save_inception("app1", {
        "03-units-of-work.md": "- **UoW-1 — a**: a\n",
        "04-testing-posture.md": "- UoW-1: Given a, When b, Then c.\n",
        "../evil.md": "nope",          # path traversal → written as basename only
        "notes.txt": "ignored",        # non-md → skipped
    })
    d = tmp_path / "specs" / "app1" / "inception"
    assert (d / "03-units-of-work.md").exists() and (d / "04-testing-posture.md").exists()
    assert not (d / "notes.txt").exists()
    assert not (tmp_path / "specs" / "app1" / "evil.md").exists()  # no traversal escape
    assert res["ok"] and res["warnings"] == []     # UoW-1 has a G/W/T statement
    trail = [json.loads(x) for x in (d / "aidlc_trace.jsonl").read_text().splitlines()]
    assert trail[-1]["event"] == "inception.human_approved"


def test_save_inception_reuses_the_runs_trace_id(tmp_path, monkeypatch):
    monkeypatch.setattr(J, "WORKSPACE", tmp_path)
    d = tmp_path / "specs" / "app1" / "inception"
    d.mkdir(parents=True)
    (d / "aidlc_trace.jsonl").write_text(json.dumps({"trace": "aidlc-run123", "event": "inception.ready"}) + "\n")
    J.save_inception("app1", {"01-intent.md": "x"})
    trail = [json.loads(x) for x in (d / "aidlc_trace.jsonl").read_text().splitlines()]
    assert trail[-1]["event"] == "inception.human_approved"
    assert trail[-1]["trace"] == "aidlc-run123"     # correlated with the run
