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


# ---- the same asymmetry, found again: the clarify RESUME ----------------------

@pytest.mark.parametrize("fn", _ENTRYPOINTS)
def test_every_pipeline_can_build_a_confirmed_spec(fn):
    """M10 gave the clarify gate a resume — on `area run` only.

    So a clone that stopped at the gate could record a confirmation
    (`area clarify <name> --confirm-all`) and then had no way to BUILD it: `area clone`
    would re-investigate the reference, producing a different spec with a different
    digest and expiring the confirmation it had just been given, while
    `area run --use-spec` has no `reference` parameter and so cannot build in parity
    mode at all. The gate was answerable on one flow in three — the identical shape to
    `--strict` being inert on two, and found the same way.
    """
    assert "use_spec" in inspect.signature(getattr(P, fn)).parameters, (
        f"{fn} cannot build an already-confirmed spec, so the clarify gate has no "
        "resume on this flow"
    )


@pytest.mark.parametrize("cmd", ["run", "clone", "intake"])
def test_every_command_with_a_clarify_gate_offers_the_resume(cmd):
    """The CLI half: a flag the operator cannot type is not a resume."""
    from area.cli import _build_parser

    parser = _build_parser()
    sub = next(a for a in parser._actions if getattr(a, "choices", None)
               and cmd in a.choices)
    opts = {o for action in sub.choices[cmd]._actions for o in action.option_strings}
    assert "--use-spec" in opts, f"`area {cmd}` has no --use-spec"
    assert "--strict" in opts, f"`area {cmd}` has no --strict"
