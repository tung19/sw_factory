"""Requirement-ambiguity handling: user-provided EXPECTED RESULTS (become
acceptance criteria), the spec stage's ASSUMPTIONS ledger, and the --clarify
gate that stops before building on MATERIAL ambiguity. Pure logic — no agents."""
import types
from pathlib import Path

import area.cli as cli
import area.pipeline as P
import area.spec.extract as E
import area.web.jobs as J


def test_expected_block_empty():
    assert E.expected_block(None) == "" and E.expected_block("   ") == ""


def test_expected_block_is_authoritative():
    b = E.expected_block("calcTip(100,15)=15")
    assert "AUTHORITATIVE" in b and "calcTip(100,15)=15" in b


def test_load_assumptions(tmp_path):
    (tmp_path / "assumptions.yaml").write_text(
        "assumptions:\n"
        "  - {question: Q1, assumption: A1, material: true}\n"
        "  - {question: Q2, assumption: A2, material: false}\n"
    )
    xs = E.load_assumptions(tmp_path)
    assert len(xs) == 2 and xs[0]["question"] == "Q1"


def test_load_assumptions_missing_or_bad(tmp_path):
    assert E.load_assumptions(tmp_path) == []
    (tmp_path / "assumptions.yaml").write_text("not: a list\n")
    assert E.load_assumptions(tmp_path) == []


def test_clarify_gate_filters_material(tmp_path):
    specs = tmp_path / "specs" / "app"
    specs.mkdir(parents=True)
    (specs / "assumptions.yaml").write_text(
        "assumptions:\n"
        "  - {question: Q1, assumption: A1, material: true}\n"
        "  - {question: Q2, assumption: A2, material: false}\n"
    )
    qs = P._clarify_gate(tmp_path, "app", True)
    assert len(qs) == 1 and qs[0]["question"] == "Q1"
    assert P._clarify_gate(tmp_path, "app", False) == []  # off -> never asks


def test_run_pipeline_clarify_stops_before_build(monkeypatch, tmp_path):
    spec = types.SimpleNamespace(features=[1], model_dump=lambda: {})
    acc = types.SimpleNamespace(criteria=[1], model_dump=lambda: {})

    def fake_extract(req, out, **kw):
        Path(out).mkdir(parents=True, exist_ok=True)
        (Path(out) / "assumptions.yaml").write_text(
            "assumptions:\n  - {question: Q, assumption: A, material: true}\n"
        )
        return spec, acc

    monkeypatch.setattr(P, "extract_spec", fake_extract)
    monkeypatch.setattr(P, "_build", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must NOT build when clarify stops")))
    res = P.run_pipeline("do x", name="app", clarify=True, workspace=tmp_path)
    assert res.clarify_needed and not res.passed and res.questions


def test_run_pipeline_without_clarify_builds(monkeypatch, tmp_path):
    spec = types.SimpleNamespace(features=[1], model_dump=lambda: {})
    acc = types.SimpleNamespace(criteria=[1], model_dump=lambda: {})
    monkeypatch.setattr(P, "extract_spec", lambda req, out, **kw: (spec, acc))
    built = []
    monkeypatch.setattr(
        P, "_build",
        lambda name, s, a, root, *a2, **k: (
            built.append(1),
            P.PipelineResult(name, s, a, root, root, True),
        )[1],
    )
    res = P.run_pipeline("do x", name="app", clarify=False, workspace=tmp_path)
    assert res.passed and built and not res.clarify_needed


def test_finish_clarify_returns_code_2(tmp_path):
    res = types.SimpleNamespace(
        clarify_needed=True, name="app", spec_dir=tmp_path, app_dir=tmp_path,
        passed=False, questions=[],
    )
    assert cli._finish(res, types.SimpleNamespace()) == 2


def test_jobs_flags_carry_expect_and_clarify():
    f = J.JobManager._flags({"expected": "calcTip(100,15)=15", "clarify": True})
    assert "--clarify" in f
    assert "--expect" in f and "calcTip(100,15)=15" in f
