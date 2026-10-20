"""Recommendation #1 (clarify DEFAULT-ON) + #2 (INDEPENDENT spec-vs-intent review).

Pure logic + injected fakes — no real agents. Proves the independent reviewer can
catch a MATERIAL ambiguity the spec stage missed and force the clarify gate to stop
the build, and that clarify/spec-review default on at the CLI with --no-* opt-outs.
"""
import types
from pathlib import Path

import area.cli
import area.pipeline as P
import area.spec.extract as E
import area.spec.review as R
import area.web.jobs as J


# ---------- _parse_review (pure) ----------
def test_parse_review_after_sentinel_filters_nonmaterial():
    raw = (
        "prose the model may add\n"
        f"{R.SENTINEL}\n"
        "- question: Who is the primary user?\n"
        "  assumption: a single admin\n"
        "  material: true\n"
        "- question: a nitpick\n"
        "  assumption: x\n"
        "  material: false\n"
    )
    xs = R._parse_review(raw)
    assert len(xs) == 1
    assert xs[0]["question"].startswith("Who")
    assert xs[0]["material"] is True and xs[0]["source"] == "independent-review"


def test_parse_review_code_fence_and_junk():
    assert R._parse_review(f"{R.SENTINEL}\n```yaml\n[]\n```") == []
    assert R._parse_review("not a yaml list: {a: 1}") == []
    assert R._parse_review("") == []


# ---------- append_assumptions (pure file op) ----------
def test_append_assumptions_dedups_by_question(tmp_path):
    (tmp_path / "assumptions.yaml").write_text(
        "assumptions:\n  - {question: Q1, assumption: A1, material: true}\n"
    )
    n = E.append_assumptions(tmp_path, [
        {"question": "Q1", "assumption": "dup", "material": True},   # dup → skipped
        {"question": "Q2", "assumption": "new", "material": True},
    ])
    assert n == 1
    assert {a["question"] for a in E.load_assumptions(tmp_path)} == {"Q1", "Q2"}


def test_append_assumptions_creates_and_noop(tmp_path):
    assert E.append_assumptions(tmp_path, []) == 0
    n = E.append_assumptions(tmp_path, [{"question": "Q", "assumption": "A", "material": True}])
    assert n == 1 and (tmp_path / "assumptions.yaml").exists()


# ---------- review_spec (fail-open + injection seam) ----------
def test_review_spec_fail_open(tmp_path):
    assert R.review_spec("", tmp_path) == []            # no requirement
    assert R.review_spec("do x", tmp_path) == []        # spec files missing


def test_review_spec_degrades_when_ask_raises(tmp_path):
    (tmp_path / "spec.yaml").write_text("name: x\n")
    (tmp_path / "acceptance.yaml").write_text("criteria: []\n")

    def boom(_prompt):
        raise RuntimeError("no claude on PATH")

    assert R.review_spec("do x", tmp_path, ask=boom) == []


def test_review_spec_returns_findings(tmp_path):
    (tmp_path / "spec.yaml").write_text("name: x\n")
    (tmp_path / "acceptance.yaml").write_text("criteria: []\n")

    def ask(_prompt):
        return (f"{R.SENTINEL}\n- question: persistence?\n"
                "  assumption: in-memory\n  material: true\n")

    xs = R.review_spec("a notes app", tmp_path, ask=ask)
    assert len(xs) == 1 and xs[0]["question"] == "persistence?"


# ---------- pipeline: independent reviewer catches a MISSED ambiguity ----------
def test_independent_review_forces_clarify_stop(monkeypatch, tmp_path):
    spec = types.SimpleNamespace(features=[1], model_dump=lambda: {})
    acc = types.SimpleNamespace(criteria=[1], model_dump=lambda: {})

    def fake_extract(req, out, **kw):
        Path(out).mkdir(parents=True, exist_ok=True)
        (Path(out) / "assumptions.yaml").write_text("assumptions: []\n")  # spec flags NOTHING
        (Path(out) / "spec.yaml").write_text("name: x\n")
        (Path(out) / "acceptance.yaml").write_text("criteria: []\n")
        return spec, acc

    monkeypatch.setattr(P, "extract_spec", fake_extract)
    # the INDEPENDENT reviewer finds a material ambiguity the spec stage missed
    monkeypatch.setattr(P, "review_spec", lambda req, sd, **kw: [
        {"question": "who is the user?", "assumption": "admin", "material": True}])
    monkeypatch.setattr(P, "_build", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must NOT build — the reviewer should force a clarify stop")))

    res = P.run_pipeline("vague thing", name="app", clarify=True, spec_review=True,
                         workspace=tmp_path)
    assert res.clarify_needed and not res.passed
    assert any("who is the user" in q["question"] for q in res.questions)


def test_spec_review_default_off_in_lib_builds(monkeypatch, tmp_path):
    spec = types.SimpleNamespace(features=[1], model_dump=lambda: {})
    acc = types.SimpleNamespace(criteria=[1], model_dump=lambda: {})
    monkeypatch.setattr(P, "extract_spec", lambda req, out, **kw: (spec, acc))
    monkeypatch.setattr(P, "review_spec", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("review must NOT run when spec_review=False")))
    built = []
    monkeypatch.setattr(P, "_build", lambda name, s, a, root, *a2, **k: (
        built.append(1), P.PipelineResult(name, s, a, root, root, True))[1])
    # clarify defaults True, but spec_review defaults False in the library → no review
    res = P.run_pipeline("do x", name="app", workspace=tmp_path)
    assert res.passed and built


# ---------- CLI: clarify + spec-review default ON, --no-* opt-outs ----------
def _res(tmp_path):
    return types.SimpleNamespace(passed=True, name="app", spec_dir=tmp_path, app_dir=tmp_path)


def test_cli_clarify_and_spec_review_default_on(monkeypatch, tmp_path):
    cap = {}
    monkeypatch.setattr(area.pipeline, "run_pipeline",
                        lambda req, **kw: (cap.update(kw), _res(tmp_path))[1])
    area.cli.main(["run", "x", "--name", "t"])
    assert cap["clarify"] is True and cap["spec_review"] is True


def test_cli_no_clarify_no_spec_review(monkeypatch, tmp_path):
    cap = {}
    monkeypatch.setattr(area.pipeline, "run_pipeline",
                        lambda req, **kw: (cap.update(kw), _res(tmp_path))[1])
    area.cli.main(["run", "x", "--name", "t", "--no-clarify", "--no-spec-review"])
    assert cap["clarify"] is False and cap["spec_review"] is False


# ---------- jobs: emit --no-* only on explicit opt-out ----------
def test_jobs_flags_optouts():
    on = J.JobManager._flags({"clarify": True, "spec_review": True})
    assert "--clarify" in on and "--spec-review" in on
    off = J.JobManager._flags({"clarify": False, "spec_review": False})
    assert "--no-clarify" in off and "--no-spec-review" in off
    absent = J.JobManager._flags({})
    assert not {"--clarify", "--no-clarify", "--spec-review", "--no-spec-review"} & set(absent)
