"""B1 (deep audit 2026-10-28): `--use-spec` must NOT re-run the spec reviewer.

`--use-spec` skips re-EXTRACTION so a confirmed spec's digest stays stable — that is how
`area clarify` + `--use-spec` resumes a build that stopped at the clarify gate. But the
independent reviewer step ran regardless of `use_spec`, and the reviewer is a
non-deterministic LLM that MUTATES `assumptions.yaml`, which is part of `spec_digest`,
which the clarify confirmation is anchored on. So rebuilding a confirmed spec with
`--use-spec --spec-review` (spec_review defaults on) could change the digest, expire the
confirmation, and re-wall the operator at the gate — defeating the resume it just used.

The reviewer must be skipped when reusing a confirmed spec, on every pipeline that offers
both flags.
"""
import pytest

from area import pipeline as P
from area.spec.models import Acceptance, Spec

_ENTRYPOINTS = ("run_pipeline", "clone_pipeline", "intake_pipeline")


def _stub(monkeypatch):
    spec, acc = Spec(name="a", summary="s"), Acceptance()
    monkeypatch.setattr(P, "extract_spec", lambda *a, **k: (spec, acc))
    monkeypatch.setattr(P, "spec_from_source", lambda *a, **k: (spec, acc), raising=False)
    import area.intake as _intake

    monkeypatch.setattr(_intake, "spec_from_aidlc", lambda *a, **k: (spec, acc))
    monkeypatch.setattr(_intake, "emit_evidence", lambda *a, **k: None)
    monkeypatch.setattr(
        P, "_build",
        lambda name, spec, acc, root, *a, **k: P.PipelineResult(
            name, spec, acc, root / "specs" / name, root / "apps" / name, True))
    monkeypatch.setattr(P, "_maybe_design", lambda *a, **k: None)
    monkeypatch.setattr(P, "_clarify_gate", lambda *a, **k: [])
    monkeypatch.setattr(P, "_resolve_clone_reference", lambda *a, **k: None,
                        raising=False)
    calls: list[int] = []
    monkeypatch.setattr(P, "_spec_review_step", lambda *a, **k: (calls.append(1), 0)[1])
    return calls


def _drive(fn, tmp_path, **kw):
    common = dict(name="a", workspace=tmp_path, clarify=False, spec_review=True)
    if fn == "run_pipeline":
        return P.run_pipeline("a requirement", **common, **kw)
    if fn == "clone_pipeline":
        return P.clone_pipeline(str(tmp_path / "ref"), **common, **kw)
    (tmp_path / "artifacts").mkdir(exist_ok=True)
    return P.intake_pipeline(str(tmp_path / "artifacts"), **common, **kw)


@pytest.mark.parametrize("fn", _ENTRYPOINTS)
def test_use_spec_skips_the_reviewer(fn, monkeypatch, tmp_path):
    calls = _stub(monkeypatch)
    _drive(fn, tmp_path, use_spec=True)
    assert calls == [], (
        f"{fn} re-ran the spec reviewer under --use-spec; it mutates assumptions.yaml "
        "and would void the clarify confirmation the resume just honored"
    )


@pytest.mark.parametrize("fn", _ENTRYPOINTS)
def test_without_use_spec_the_reviewer_still_runs(fn, monkeypatch, tmp_path):
    """The reviewer is valuable on a FRESH build — only reuse must skip it."""
    calls = _stub(monkeypatch)
    _drive(fn, tmp_path, use_spec=False)
    assert calls == [1], f"{fn} skipped the reviewer on a fresh (non-reuse) build"
