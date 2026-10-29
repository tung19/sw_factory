"""Flow A `--research`: `area run --research` surveys comparable OSS (top-N by
stars/quality) and folds their patterns INTO the spec prompt before building — the
requirement stays authoritative and the oracle-loop is unchanged.

The brief informs `extract_spec` as PROMPT CONTEXT (like expected_block), it is NOT a
mechanical feature merge — so the LLM writes a coherent spec+acceptance that keeps the
feature↔AC coverage invariant (`validate_cross`) by construction. All agent steps are
monkeypatched; this proves the WIRING, agent-free.
"""
from pathlib import Path

import area.pipeline as P
from area.research import RepoAnalysis, ResearchBrief, research_block
from area.spec.models import Acceptance, Spec


def _brief():
    return ResearchBrief(
        reference="", requirement="a todo app", candidates_considered=87,
        top=[
            RepoAnalysis(repo="a/todo", url="u1", score=9.0,
                         features=["add todo", "mark done", "filter active"]),
            RepoAnalysis(repo="b/tasks", url="u2", score=8.0, features=["due dates"]),
        ])


# ── research_block: the prompt context formatter ────────────────────────────────
def test_research_block_lists_features_and_keeps_requirement_authoritative():
    blk = research_block(_brief())
    assert "a/todo" in blk and "mark done" in blk
    assert "authoritative" in blk.lower()      # requirement wins, do not invent scope


def test_research_block_empty_brief_is_empty_string():
    assert research_block(ResearchBrief(reference="", requirement="q",
                                        candidates_considered=0, top=[])) == ""


# ── wiring: run_pipeline(research=True) feeds the brief into extract_spec ────────
def _stub_build(monkeypatch, captured, *, fake_research):
    monkeypatch.setattr(P.obs, "set_app", lambda *a, **k: None)
    monkeypatch.setattr("area.research.research", fake_research)
    monkeypatch.setattr("area.spec.clarify.answers_block", lambda d: "")

    def fake_extract(requirement, out_dir, *, expected=None, research=None, **k):
        captured["research"] = research
        captured["called"] = True
        return Spec(name="x", summary="s"), Acceptance()

    monkeypatch.setattr(P, "extract_spec", fake_extract)
    monkeypatch.setattr(P, "_spec_review_step", lambda *a, **k: None)
    monkeypatch.setattr(P, "_clarify_gate", lambda *a, **k: [])
    monkeypatch.setattr(P, "_maybe_design", lambda *a, **k: None)
    monkeypatch.setattr(P, "_build", lambda name, spec, acc, root, *a, **k: P.PipelineResult(
        name=name, spec=spec, acceptance=acc, spec_dir=root, app_dir=root, passed=True))


def test_run_with_research_folds_brief_into_extract(monkeypatch, tmp_path):
    calls = {}
    captured = {}

    def fake_research(reference, requirement, **k):
        calls["ref"] = reference
        calls["req"] = requirement
        return _brief()

    _stub_build(monkeypatch, captured, fake_research=fake_research)
    P.run_pipeline("a todo app", name="td", target="plain", research=True,
                   workspace=tmp_path)

    assert calls.get("req") == "a todo app"      # research ran on the requirement
    assert captured["research"] and "mark done" in captured["research"]   # fed in


def test_run_without_research_does_not_research(monkeypatch, tmp_path):
    captured = {}

    def boom(*a, **k):
        raise AssertionError("research must not run without --research")

    _stub_build(monkeypatch, captured, fake_research=boom)
    P.run_pipeline("a todo app", name="td2", target="plain", workspace=tmp_path)

    assert captured["called"] is True
    assert captured["research"] is None          # no research context


def test_research_brief_is_cached_and_reused_not_repaid(monkeypatch, tmp_path):
    # a clarify re-run must NOT pay for research again: a cached brief.json is reused.
    captured = {}
    n = {"runs": 0}

    def once(reference, requirement, *, workspace=None, **k):
        n["runs"] += 1
        ws = Path(workspace)
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "brief.json").write_text(
            '{"reference":"","requirement":"q","candidates_considered":5,'
            '"top":[{"repo":"a/todo","url":"u","score":9,"features":["add todo"]}]}')
        return _brief()

    _stub_build(monkeypatch, captured, fake_research=once)
    P.run_pipeline("a todo app", name="td3", target="plain", research=True,
                   workspace=tmp_path)
    P.run_pipeline("a todo app", name="td3", target="plain", research=True,
                   workspace=tmp_path)
    assert n["runs"] == 1                         # second run reused the cached brief
    assert captured["research"] and "add todo" in captured["research"]


# ── CLI: `area run --research [--research-top N]` is exposed and threaded ─────────
def test_cli_run_exposes_research_flags():
    from area.cli import _build_parser

    ns = _build_parser().parse_args(
        ["run", "a todo app", "--name", "td", "--research", "--research-top", "3"])
    assert ns.research is True and ns.research_top == 3


def test_cli_run_defaults_research_off():
    from area.cli import _build_parser

    ns = _build_parser().parse_args(["run", "a todo app", "--name", "td"])
    assert ns.research is False and ns.research_top == 5
