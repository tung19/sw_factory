"""`--strict` must mean the same thing on every flow that offers it.

Found by auditing the seams where the same day's work met a flow it had never run.
`--strict` now also governs **oracle strength** (a criterion declaring
`verify_by: execution` whose test only reads the source blocks at authoring time,
M11). That was threaded through `run_pipeline` and nowhere else — so
`area clone --strict` and `area intake --strict` ACCEPTED the flag and silently did
not apply it. A flag that is accepted and does nothing is worse than a missing one:
the operator believes they asked for the stricter posture.

This is a generic guard rather than three ad-hoc tests, because the failure mode is
"someone adds a fourth entrypoint and forgets". It asserts the contract — every
pipeline that takes `strict` hands it to the build — against the real call graph,
with only the agent stages stubbed.
"""
import inspect

import pytest

from area import pipeline as P

# Every pipeline entrypoint whose CLI command exposes --strict.
_ENTRYPOINTS = ("run_pipeline", "clone_pipeline", "intake_pipeline")


@pytest.mark.parametrize("fn", _ENTRYPOINTS)
def test_every_pipeline_accepts_strict(fn):
    assert "strict" in inspect.signature(getattr(P, fn)).parameters, (
        f"{fn} does not accept `strict`, so the CLI flag cannot reach the build"
    )


@pytest.mark.parametrize("fn", _ENTRYPOINTS)
def test_every_pipeline_hands_strict_to_the_build(fn, monkeypatch, tmp_path):
    """Driven through the real function with the agent stages stubbed, so this
    measures the call graph rather than the source text."""
    seen: dict[str, object] = {}

    def spy_build(name, spec, acc, root, target, backend, model, build_iters, **kw):
        seen.update(kw)
        return P.PipelineResult(name, spec, acc, root / "specs" / name,
                                root / "apps" / name, True)

    monkeypatch.setattr(P, "_build", spy_build)
    monkeypatch.setattr(P, "_maybe_design", lambda *a, **k: None)
    monkeypatch.setattr(P, "_clarify_gate", lambda *a, **k: [])
    monkeypatch.setattr(P, "_spec_review_step", lambda *a, **k: None, raising=False)

    from area.spec.models import Acceptance, Spec

    spec, acc = Spec(name="a", summary="s"), Acceptance()
    monkeypatch.setattr(P, "extract_spec", lambda *a, **k: (spec, acc))
    monkeypatch.setattr(P, "spec_from_source", lambda *a, **k: (spec, acc),
                        raising=False)
    import area.intake as _intake

    monkeypatch.setattr(_intake, "spec_from_aidlc", lambda *a, **k: (spec, acc))
    monkeypatch.setattr(_intake, "emit_evidence", lambda *a, **k: None)
    monkeypatch.setattr(P, "_resolve_clone_reference", lambda *a, **k: None,
                        raising=False)
    monkeypatch.setattr(P, "review_spec", lambda *a, **k: [], raising=False)

    kwargs: dict[str, object] = {"name": "a", "workspace": tmp_path, "strict": True,
                                 "clarify": False}
    if fn == "run_pipeline":
        args: tuple = ("a requirement",)
    elif fn == "clone_pipeline":
        args = (str(tmp_path / "ref"),)
    else:
        (tmp_path / "artifacts").mkdir(exist_ok=True)
        args = (str(tmp_path / "artifacts"),)   # intake takes a PATH, not a dict

    # Deliberately NOT wrapped in a skip: `intake_pipeline` was one of the two flows
    # where --strict was inert, so a skip here would hide exactly what this pins.
    getattr(P, fn)(*args, **kwargs)

    assert seen.get("strict") is True, (
        f"{fn} did not pass strict to the build — `--strict` is inert on this flow"
    )
