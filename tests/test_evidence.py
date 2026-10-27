"""PR8 Phase 3 — one correlated audit trail per app. Construction events emit
into the spec-dir trail under the Inception run's origin trace; read_trail merges
the Inception sub-trail + the spec-dir trail in time order."""
import json

import area.cli as CLI
import area.evidence as EV


def _inc(tmp_path, name="app1"):
    d = tmp_path / "specs" / name / "inception"
    d.mkdir(parents=True)
    return d


def test_current_trace_prefers_inception_origin(tmp_path, monkeypatch):
    monkeypatch.setattr("area.pipeline.WORKSPACE", tmp_path)
    inc = _inc(tmp_path)
    (inc / "aidlc_trace.jsonl").write_text(
        json.dumps({"trace": "aidlc-origin", "event": "inception.ready", "ts": 1}) + "\n")
    assert EV.current_trace("app1") == "aidlc-origin"


def test_current_trace_mints_when_none(tmp_path, monkeypatch):
    monkeypatch.setattr("area.pipeline.WORKSPACE", tmp_path)
    assert EV.current_trace("fresh").startswith("aidlc-")


def test_emit_appends_under_the_origin_trace(tmp_path, monkeypatch):
    monkeypatch.setattr("area.pipeline.WORKSPACE", tmp_path)
    inc = _inc(tmp_path)
    (inc / "aidlc_trace.jsonl").write_text(
        json.dumps({"trace": "aidlc-origin", "event": "inception.ready", "ts": 1}) + "\n")
    EV.emit("app1", "build.green", {"target": "plain"})
    rec = json.loads((tmp_path / "specs" / "app1" / "aidlc_trace.jsonl").read_text().splitlines()[-1])
    assert rec["event"] == "build.green"
    assert rec["trace"] == "aidlc-origin"          # Construction correlates to Inception
    assert rec["data"]["target"] == "plain"


def test_read_trail_merges_inception_and_spec_in_time_order(tmp_path, monkeypatch):
    monkeypatch.setattr("area.pipeline.WORKSPACE", tmp_path)
    sd = tmp_path / "specs" / "app1"
    inc = _inc(tmp_path)
    (inc / "aidlc_trace.jsonl").write_text(
        json.dumps({"trace": "t", "event": "inception.start", "ts": 1}) + "\n"
        + json.dumps({"trace": "t", "event": "inception.ready", "ts": 2}) + "\n")
    (sd / "aidlc_trace.jsonl").write_text(
        json.dumps({"trace": "t", "event": "build.green", "ts": 3}) + "\n"
        + json.dumps({"trace": "t", "event": "gate", "ts": 4, "data": {"gate": "audit", "ok": True}}) + "\n")
    events = [r["event"] for r in EV.read_trail("app1")]
    assert events == ["inception.start", "inception.ready", "build.green", "gate"]


def test_read_trail_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("area.pipeline.WORKSPACE", tmp_path)
    assert EV.read_trail("none") == []


def test_cli_trace_reports_the_chain(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("area.pipeline.WORKSPACE", tmp_path)
    assert CLI.main(["trace", "none"]) == 1          # no trail → exit 1
    sd = tmp_path / "specs" / "app1"
    sd.mkdir(parents=True)
    (sd / "aidlc_trace.jsonl").write_text(
        json.dumps({"trace": "t", "event": "build.green", "ts": 1}) + "\n")
    assert CLI.main(["trace", "app1"]) == 0
    assert "build.green" in capsys.readouterr().out
