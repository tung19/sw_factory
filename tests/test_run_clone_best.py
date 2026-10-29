"""`area run --clone-best`: the discovery→parity bridge. Research surveys comparable
OSS, picks the single highest-ranked repo, and hands IT to Flow B (`clone_pipeline`)
for a parity rebuild — instead of synthesizing a fresh Flow A spec.

Use when you don't yet know which app to clone: research finds it, clone reproduces it.
All agent steps (research + clone) are monkeypatched; this proves the WIRING, agent-free.
"""
import pytest

import area.pipeline as P
from area.research import RepoAnalysis, ResearchBrief
from area.spec.models import Acceptance, Spec


def _brief(*repos):
    return ResearchBrief(reference="", requirement="a kanban app",
                         candidates_considered=50, top=list(repos))


def _canned_clone_result(name, root):
    return P.PipelineResult(name=name, spec=Spec(name=name, summary="s"),
                            acceptance=Acceptance(), spec_dir=root, app_dir=root,
                            passed=True)


def _stub(monkeypatch, *, brief, seen):
    monkeypatch.setattr(P.obs, "set_app", lambda *a, **k: None)
    monkeypatch.setattr("area.research.research",
                        lambda reference, requirement, **k: brief)

    def fake_clone(source, *, name="clone", **k):
        seen["source"] = source
        seen["kind"] = k.get("kind")
        return _canned_clone_result(name, k.get("workspace"))

    monkeypatch.setattr(P, "clone_pipeline", fake_clone)
    # Flow A extract must NOT run on the clone-best path.
    monkeypatch.setattr(P, "extract_spec",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("extract_spec must not run for --clone-best")))


def test_clone_best_clones_the_highest_ranked_repo(monkeypatch, tmp_path):
    seen = {}
    brief = _brief(
        RepoAnalysis(repo="lo/kan", url="https://github.com/lo/kan", score=4.0),
        RepoAnalysis(repo="hi/board", url="https://github.com/hi/board", score=9.5),
        RepoAnalysis(repo="mid/t", url="https://github.com/mid/t", score=7.0),
    )
    _stub(monkeypatch, brief=brief, seen=seen)
    res = P.run_pipeline("a kanban app", name="kb", target="plain",
                         clone_best=True, workspace=tmp_path)
    assert res.passed
    assert seen["source"] == "https://github.com/hi/board"   # 9.5 wins, not list order
    assert seen["kind"] == "auto"


def test_clone_best_errors_when_research_finds_nothing(monkeypatch, tmp_path):
    seen = {}
    _stub(monkeypatch, brief=_brief(), seen=seen)   # empty top
    with pytest.raises(RuntimeError, match="clone-best"):
        P.run_pipeline("a kanban app", name="kb2", target="plain",
                       clone_best=True, workspace=tmp_path)


def test_plain_run_without_clone_best_does_not_clone(monkeypatch, tmp_path):
    brief = _brief(RepoAnalysis(repo="x/y", url="u", score=1.0))
    monkeypatch.setattr(P.obs, "set_app", lambda *a, **k: None)
    monkeypatch.setattr("area.research.research",
                        lambda *a, **k: brief)
    monkeypatch.setattr(P, "clone_pipeline",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("clone must not run without --clone-best")))
    monkeypatch.setattr("area.spec.clarify.answers_block", lambda d: "")
    monkeypatch.setattr(P, "_spec_review_step", lambda *a, **k: None)
    monkeypatch.setattr(P, "_clarify_gate", lambda *a, **k: [])
    monkeypatch.setattr(P, "_maybe_design", lambda *a, **k: None)
    monkeypatch.setattr(P, "extract_spec",
                        lambda *a, **k: (Spec(name="x", summary="s"), Acceptance()))
    monkeypatch.setattr(P, "_build", lambda name, spec, acc, root, *a, **k:
                        _canned_clone_result(name, root))
    res = P.run_pipeline("a kanban app", name="kb3", target="plain", workspace=tmp_path)
    assert res.passed            # ordinary Flow A, no clone


# ── CLI ─────────────────────────────────────────────────────────────────────────
def test_cli_run_exposes_clone_best():
    from area.cli import _build_parser

    ns = _build_parser().parse_args(
        ["run", "a kanban app", "--name", "kb", "--clone-best"])
    assert ns.clone_best is True


def test_cli_clone_best_with_use_spec_is_rejected():
    import argparse

    from area.cli import _cmd_run

    ns = argparse.Namespace(requirement="x", name="kb", clone_best=True, use_spec=True)
    with pytest.raises((SystemExit, ValueError)):
        _cmd_run(ns, None)
