"""`area run --clone-pick`: human-in-the-loop clone. Research prints the top-N repos,
you choose which one, and THAT repo is cloned (Flow B) — instead of auto-picking the
highest score (`--clone-best`).

The interactive prompt lives in the CLI as an injectable chooser callback, so
`run_pipeline` stays pure and the picking logic is testable without a terminal.
"""
import argparse

import pytest

import area.pipeline as P
from area.research import RepoAnalysis, ResearchBrief
from area.spec.models import Acceptance, Spec


def _brief(*repos):
    return ResearchBrief(reference="", requirement="a kanban app",
                         candidates_considered=50, top=list(repos))


def _stub_clone(monkeypatch, *, brief, seen):
    monkeypatch.setattr(P.obs, "set_app", lambda *a, **k: None)
    monkeypatch.setattr("area.research.research",
                        lambda reference, requirement, **k: brief)

    def fake_clone(source, *, name="clone", **k):
        seen["source"] = source
        return P.PipelineResult(name=name, spec=Spec(name=name, summary="s"),
                                acceptance=Acceptance(), spec_dir=k.get("workspace"),
                                app_dir=k.get("workspace"), passed=True)

    monkeypatch.setattr(P, "clone_pipeline", fake_clone)
    monkeypatch.setattr(P, "extract_spec",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("extract must not run on the clone path")))


def test_choose_repo_overrides_the_auto_top_pick(monkeypatch, tmp_path):
    seen = {}
    brief = _brief(
        RepoAnalysis(repo="hi/board", url="https://github.com/hi/board", score=9.5),
        RepoAnalysis(repo="lo/kan", url="https://github.com/lo/kan", score=4.0),
        RepoAnalysis(repo="mid/t", url="https://github.com/mid/t", score=7.0),
    )
    _stub_clone(monkeypatch, brief=brief, seen=seen)
    # the chooser picks index 1 (lo/kan) — NOT the 9.5 auto-winner.
    P.run_pipeline("a kanban app", name="kb", target="plain", clone_best=True,
                   choose_repo=lambda repos: 1, workspace=tmp_path)
    assert seen["source"] == "https://github.com/lo/kan"


def test_no_chooser_falls_back_to_highest_score(monkeypatch, tmp_path):
    seen = {}
    brief = _brief(
        RepoAnalysis(repo="lo/kan", url="https://github.com/lo/kan", score=4.0),
        RepoAnalysis(repo="hi/board", url="https://github.com/hi/board", score=9.5),
    )
    _stub_clone(monkeypatch, brief=brief, seen=seen)
    P.run_pipeline("a kanban app", name="kb2", target="plain", clone_best=True,
                   workspace=tmp_path)
    assert seen["source"] == "https://github.com/hi/board"      # auto max-score


# ── the interactive chooser (CLI), input injected ───────────────────────────────
def _repos():
    return [RepoAnalysis(repo="a/one", url="u1", score=9.0, features=["x"]),
            RepoAnalysis(repo="b/two", url="u2", score=8.0),
            RepoAnalysis(repo="c/three", url="u3", score=7.0)]


def test_chooser_parses_a_valid_pick():
    from area.cli import _repo_chooser

    choose = _repo_chooser(read=lambda _p: "2")
    assert choose(_repos()) == 1            # "2" (1-based) → index 1


def test_chooser_defaults_to_first_on_empty():
    from area.cli import _repo_chooser

    choose = _repo_chooser(read=lambda _p: "")
    assert choose(_repos()) == 0


def test_chooser_reprompts_on_out_of_range_then_accepts():
    from area.cli import _repo_chooser

    answers = iter(["9", "0", "abc", "3"])
    choose = _repo_chooser(read=lambda _p: next(answers))
    assert choose(_repos()) == 2            # first valid in-range pick is "3" → index 2


# ── CLI ─────────────────────────────────────────────────────────────────────────
def test_cli_run_exposes_clone_pick():
    from area.cli import _build_parser

    ns = _build_parser().parse_args(["run", "a kanban app", "--name", "kb", "--clone-pick"])
    assert ns.clone_pick is True


def test_cli_clone_pick_non_interactive_is_rejected(monkeypatch):
    import sys

    from area.cli import _cmd_run

    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    ns = argparse.Namespace(requirement="x", name="kb", clone_best=False,
                            clone_pick=True, use_spec=False)
    with pytest.raises(SystemExit):
        _cmd_run(ns, None)
