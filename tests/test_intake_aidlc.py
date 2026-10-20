"""#3 — the Hybrid seam: AI-DLC artifact ingestion, the correlation trace used
to emit Construction evidence back into AI-DLC's audit trail, and CLI wiring."""
import json
import types

import pytest

import area.cli
import area.pipeline
from area.intake import (
    emit_evidence,
    load_aidlc_artifacts,
    new_trace_id,
)


def test_load_artifacts_dir_concats_text_only(tmp_path):
    (tmp_path / "a.md").write_text("# Requirements\nUser can add a todo\n")
    (tmp_path / "b.yaml").write_text("units: [add-todo]\n")
    (tmp_path / "ignore.png").write_bytes(b"\x89PNG\r\n")
    blob = load_aidlc_artifacts(tmp_path)
    assert "add a todo" in blob and "units" in blob
    assert "a.md" in blob and "ignore.png" not in blob


def test_load_artifacts_single_file(tmp_path):
    f = tmp_path / "inception.md"
    f.write_text("hello units of work")
    assert "hello units of work" in load_aidlc_artifacts(f)


def test_load_artifacts_empty_or_missing_raises(tmp_path):
    with pytest.raises(RuntimeError):
        load_aidlc_artifacts(tmp_path)              # dir with no artifacts
    with pytest.raises(RuntimeError):
        load_aidlc_artifacts(tmp_path / "missing")  # nonexistent


def test_load_artifacts_is_bounded(tmp_path):
    (tmp_path / "big.md").write_text("x" * 100_000)
    blob = load_aidlc_artifacts(tmp_path, max_chars=1000)
    assert len(blob) <= 1200  # header + bounded slice, not the full 100k


def test_trace_id_format_and_evidence_trail(tmp_path):
    t = new_trace_id()
    assert t.startswith("aidlc-") and len(t) > 6
    emit_evidence(tmp_path, t, "intake.start", {"k": 1})
    emit_evidence(tmp_path, t, "construction.done", {"passed": True})
    lines = (tmp_path / "aidlc_trace.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2
    rec = json.loads(lines[0])
    assert rec["trace"] == t and rec["event"] == "intake.start" and rec["data"]["k"] == 1


def test_emit_evidence_never_raises_on_bad_dir(tmp_path):
    # pointing at a path under a file (not a dir) must not blow up a build
    f = tmp_path / "f"
    f.write_text("x")
    emit_evidence(f / "nope", new_trace_id(), "x")  # no exception


def test_intake_cli_threads_tdd(monkeypatch, tmp_path):
    cap = {}

    def fake(artifacts, **kw):
        cap.update(kw, artifacts=artifacts)
        return types.SimpleNamespace(
            passed=True, name="i", spec_dir=tmp_path, app_dir=tmp_path
        )

    monkeypatch.setattr(area.pipeline, "intake_pipeline", fake)
    assert area.cli.main(["intake", "/some/aidlc", "--name", "ig", "--tdd"]) == 0
    assert cap["tdd"] is True and cap["artifacts"] == "/some/aidlc"


def _spec_acc():
    return (
        types.SimpleNamespace(features=[], model_dump=lambda: {"s": 1}),
        types.SimpleNamespace(criteria=[], model_dump=lambda: {"a": 1}),
    )


def test_clone_tdd_passes_parity_reference(monkeypatch, tmp_path):
    cap = {}
    monkeypatch.setattr(area.pipeline, "spec_from_source",
                        lambda src, out, **k: _spec_acc())

    def fake_build(name, spec, acc, root, target, backend, model, build_iters,
                   tdd=False, reference=None):
        cap.update(tdd=tdd, reference=reference)
        return area.pipeline.PipelineResult(
            name, spec, acc, root / "specs" / name, root / "apps" / name, True
        )

    monkeypatch.setattr(area.pipeline, "_build", fake_build)
    area.pipeline.clone_pipeline("/repo/x", name="c", tdd=True, workspace=tmp_path)
    assert cap["tdd"] is True
    assert cap["reference"] and "/repo/x" in cap["reference"]


def test_clone_without_tdd_has_no_reference(monkeypatch, tmp_path):
    cap = {}
    monkeypatch.setattr(area.pipeline, "spec_from_source",
                        lambda src, out, **k: _spec_acc())

    def fake_build(name, spec, acc, root, target, backend, model, build_iters,
                   tdd=False, reference=None):
        cap.update(tdd=tdd, reference=reference)
        return area.pipeline.PipelineResult(
            name, spec, acc, root / "specs" / name, root / "apps" / name, True
        )

    monkeypatch.setattr(area.pipeline, "_build", fake_build)
    area.pipeline.clone_pipeline("/repo/x", name="c", tdd=False, workspace=tmp_path)
    assert cap["tdd"] is False and cap["reference"] is None
