"""area.pipeline — Flow A (requirement) and Flow B (clone) end to end."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

from area import obs
from area._util import safe_name
from area.build import build_app
from area.re import spec_from_source
from area.spec import Acceptance, Spec, extract_spec
from area.spec.extract import append_assumptions
from area.spec.review import review_spec

from area.paths import WORKSPACE as WORKSPACE  # noqa: E402  (single source; AREA_WORKSPACE-aware; `as` = explicit re-export for the many `from area.pipeline import WORKSPACE` sites)

if TYPE_CHECKING:
    from area.engine import Backend
    from area.research import RepoAnalysis


@dataclass
class PipelineResult:
    name: str
    spec: Spec
    acceptance: Acceptance
    spec_dir: Path
    app_dir: Path
    passed: bool
    clarify_needed: bool = False
    questions: list[dict[str, Any]] = field(default_factory=list)


def _clarify_gate(root: Path, name: str, clarify: bool) -> list[dict[str, Any]]:
    """In --clarify mode, return the MATERIAL assumptions the spec stage had to
    make (ambiguities worth asking the user about before building)."""
    if not clarify:
        return []
    from area.spec.clarify import open_questions

    # `open_questions` subtracts a human confirmation that still matches this spec's
    # digest. Without it the gate had a STOP and no RESUME: nothing the operator could
    # do would satisfy it, so the only exit was turning it off. See area/spec/clarify.py.
    return open_questions(root / "specs" / name)


def _spec_review_step(
    root: Path, name: str, requirement: str, backend: Backend, model: Optional[str]
) -> int:
    """Independent spec-vs-intent review (recommendation #2): a SEPARATE reviewer —
    not the spec author — folds any MATERIAL ambiguities the spec stage missed into
    the assumptions ledger, so the clarify gate surfaces them. Advisory + fail-open
    (it can only ADD questions, never block on its own). Returns how many were added."""
    spec_dir = root / "specs" / name
    extra = review_spec(requirement, spec_dir, backend=backend, model=model)
    n = append_assumptions(spec_dir, extra)
    if n:
        print(f"[area] spec-review: +{n} material ambiguity(ies) an INDEPENDENT "
              "reviewer flagged (merged into assumptions.yaml)")
    return n


def _clarify_result(
    name: str, spec: Spec, acc: Acceptance, root: Path, questions: list[dict[str, Any]]
) -> PipelineResult:
    spec_dir = root / "specs" / name
    print(f"\n[area] ⚠ CLARIFICATION NEEDED — {len(questions)} material "
          "assumption(s); NOT building. Confirm/override then re-run:")
    for q in questions:
        print(f"  • {q.get('question')}\n      assumed → {q.get('assumption')}")
    print("[area] Update the requirement, or pass --expect \"<examples>\", then re-run.")
    return PipelineResult(
        name, spec, acc, spec_dir, root / "apps" / name,
        passed=False, clarify_needed=True, questions=questions,
    )


def _maybe_design(
    name: str, backend: Backend, model: Optional[str], design: Optional[bool],
    spec: Optional[Spec] = None,
) -> None:
    # design=None → auto (run the architect stage for a non-trivial app); explicit
    # True/False from --design / --no-design overrides the heuristic.
    want = design if design is not None else _should_design(spec)
    if not want:
        return
    from area.design import design_stage

    print("[area] design : -> design.md")
    design_stage(name, backend=backend, model=model)


def _should_design(spec: Optional[Spec]) -> bool:
    """Heuristic (recommendation #3): a non-trivial app earns the architect stage by
    DEFAULT (data model, or several features) so the product is thought through — not
    just slapped together. Trivial single-feature apps skip it. `--design`/`--no-design`
    override."""
    try:
        features = len(getattr(spec, "features", []) or [])
        entities = len(getattr(spec, "entities", []) or [])
    except Exception:
        return False
    return entities >= 1 or features >= 3


def _build(
    name: str, spec: Spec, acc: Acceptance, root: Path, target: str, backend: Backend,
    model: Optional[str], build_iters: int, tdd: bool = False,
    reference: Optional[str] = None, ui_dir: Optional[str] = None,
    strict: bool = False,
) -> PipelineResult:
    app_dir = root / "apps" / name
    design_path = root / "specs" / name / "design.md"
    design_text = design_path.read_text() if design_path.exists() else ""

    if tdd:
        passed = _tdd_build(
            name, spec, acc, app_dir, target, backend, model, build_iters,
            design_text, reference=reference, ui_dir=ui_dir, strict=strict,
        )
    else:
        print(f"[area] build : target={target} -> {app_dir}")
        passed = build_app(
            spec, acc, app_dir, target=target, backend=backend, model=model,
            max_iters=build_iters, design=design_text, ui_dir=ui_dir,
        )
    print(f"[area]        build {'GREEN' if passed else 'NOT green'}")
    return PipelineResult(name, spec, acc, root / "specs" / name, app_dir, passed)


def _tdd_build(
    name: str, spec: Spec, acc: Acceptance, app_dir: Path, target: str,
    backend: Backend, model: Optional[str], build_iters: int, design_text: str,
    *, reference: Optional[str] = None, ui_dir: Optional[str] = None,
    max_challenges: int = 1, strict: bool = False,
) -> bool:
    """TDD: lock the independent acceptance suite FIRST, then build-to-green
    against it. If the build fails because the builder challenges a locked test
    as wrong, an independent verifier re-adjudicates + re-locks, and we rebuild
    once more (bounded by max_challenges) — tests evolve only under governance.

    `reference` (a clone's source) switches the locked suite to BEHAVIORAL
    PARITY with the original: build-to-parity, the golden oracle for clones.
    """
    import yaml as _yaml

    from area.verify.holdout import (
        author_and_lock,
        readjudicate,
        tdd_build_oracle,
    )

    acc_yaml = _yaml.safe_dump(acc.model_dump(), sort_keys=False)
    red = "author + lock PARITY tests" if reference else "author + lock acceptance tests"
    print(f"[area] tdd   : {red} BEFORE build (red)")
    app_dir.mkdir(parents=True, exist_ok=True)
    holdout, lock = author_and_lock(
        name, backend=backend, model=model, app=app_dir, acc_yaml=acc_yaml,
        reference=reference, strict=strict,
    )

    for attempt in range(max_challenges + 1):
        oracle = tdd_build_oracle(app_dir, holdout, lock, target=target)
        print(f"[area] build : target={target} tdd=True (round {attempt + 1}) -> {app_dir}")
        if build_app(
            spec, acc, app_dir, target=target, backend=backend, model=model,
            max_iters=build_iters, design=design_text, oracle=oracle, tdd=True,
            ui_dir=ui_dir,
        ):
            return True
        if attempt == max_challenges:
            break
        # Build failed — did the builder raise a legitimate test challenge?
        changed, lock = readjudicate(
            app_dir, holdout, acc_yaml, backend=backend, model=model
        )
        if not changed:
            break  # no challenge, or it was rejected: the app genuinely failed
        print("[area] tdd   : test corrected + re-locked; rebuilding")
    return False


def _research_context(requirement: str, spec_dir: Path, backend: "Backend",
                      model: Optional[str], budget: Optional[float],
                      top: int) -> Optional[str]:
    """Run (or reuse) the research stage and render its brief as spec-prompt context.

    Flow A has no reference app, so research is driven by the requirement alone. The
    brief is cached at specs/<name>/research/brief.json and REUSED on a later re-run
    (e.g. a clarify confirmation) so the agent survey is not re-paid. Any failure is
    swallowed — research only enriches the spec, it must never block the build."""
    from area.research import BRIEF_FILE, parse_brief, research, research_block
    ws = spec_dir / "research"
    cached = ws / BRIEF_FILE
    try:
        if cached.exists():
            return research_block(parse_brief(cached.read_text())) or None
        brief = research("", requirement, backend=backend, model=model,
                         budget=budget, top=top, workspace=ws)
    except Exception as e:  # noqa: BLE001
        print(f"[area] research: skipped ({e})")
        return None
    print(f"[area] research: {len(brief.top)} repo(s) folded into the spec "
          f"(from {brief.candidates_considered} considered)")
    return research_block(brief) or None


def _run_clone_best(requirement: str, *, name: str, spec_dir: Path, root: Path,
                    target: str, backend: "Backend", model: Optional[str],
                    spec_iters: int, build_iters: int, design: Optional[bool],
                    tdd: bool, clarify: bool, spec_review: bool, strict: bool,
                    research_top: int, research_budget: Optional[float],
                    choose_repo: Optional[Callable[[list["RepoAnalysis"]], int]] = None,
                    ) -> PipelineResult:
    """`--clone-best`: research comparable OSS, pick a repo, and hand it to Flow B
    (`clone_pipeline`) for a parity rebuild. `choose_repo(top)` selects the index (the
    CLI's interactive `--clone-pick`); without it, the single highest-ranked repo wins.
    The research brief is cached+reused (as for `--research`) so a re-run is not re-paid."""
    from area.research import BRIEF_FILE, parse_brief, research
    ws = spec_dir / "research"
    cached = ws / BRIEF_FILE
    if cached.exists():
        brief = parse_brief(cached.read_text())
    else:
        brief = research("", requirement, backend=backend, model=model,
                         budget=research_budget, top=research_top, workspace=ws)
    if not brief.top:
        raise RuntimeError(
            "--clone-best: research found no comparable repo to clone "
            f"(considered {brief.candidates_considered}). Run without --clone-best to "
            "build from the requirement instead.")
    if choose_repo is not None:
        idx = choose_repo(brief.top)
        best = brief.top[idx] if 0 <= idx < len(brief.top) else max(
            brief.top, key=lambda r: r.score)
    else:
        best = max(brief.top, key=lambda r: r.score)
    print(f"[area] clone-best: cloning repo {best.repo} (score {best.score:.2f}) "
          f"— {best.url}")
    return clone_pipeline(
        best.url, name=name, kind="auto", target=target, backend=backend, model=model,
        spec_iters=spec_iters, build_iters=build_iters, design=design, tdd=tdd,
        clarify=clarify, spec_review=spec_review, workspace=root, strict=strict)


def run_pipeline(
    requirement: str,
    *,
    name: str = "app",
    target: str = "cloudflare",
    backend: Backend = "acp",
    model: Optional[str] = None,
    spec_iters: int = 3,
    build_iters: int = 3,
    design: Optional[bool] = None,
    tdd: bool = False,
    expected: Optional[str] = None,
    clarify: bool = True,
    spec_review: bool = False,
    workspace: Optional[str | Path] = None,
    use_spec: bool = False,
    strict: bool = False,
    research: bool = False,
    research_top: int = 5,
    research_budget: Optional[float] = None,
    clone_best: bool = False,
    choose_repo: Optional[Callable[[list["RepoAnalysis"]], int]] = None,
) -> PipelineResult:
    """Flow A: requirement -> spec -> [independent review] -> [clarify] -> [design] -> build.

    `clarify` defaults ON (recommendation #1): a vague requirement STOPS at the spec
    on material ambiguity instead of silently guessing + building. `spec_review` adds
    an independent spec-vs-intent reviewer (recommendation #2) before the gate.
    """
    name = safe_name(name)
    obs.set_app(name)  # scope this build's agent-run cost to this app (cost gate)
    root = Path(workspace) if workspace else WORKSPACE
    spec_dir = root / "specs" / name
    # Discovery → parity bridge: research finds the best comparable repo, then Flow B
    # CLONES it (parity rebuild) instead of synthesizing a fresh Flow A spec.
    if clone_best and not use_spec:
        return _run_clone_best(
            requirement, name=name, spec_dir=spec_dir, root=root, target=target,
            backend=backend, model=model, spec_iters=spec_iters,
            build_iters=build_iters, design=design, tdd=tdd, clarify=clarify,
            spec_review=spec_review, strict=strict, research_top=research_top,
            research_budget=research_budget, choose_repo=choose_repo)
    if not use_spec:
        print(f"[area] spec   : {requirement!r}")
    # A human's typed answers are authoritative input to a re-extraction, so the
    # extractor stops re-guessing what they already decided.
    from area.spec.clarify import answers_block

    answered = answers_block(spec_dir)
    # Flow A opt-in: survey comparable OSS and fold their patterns into the spec PROMPT
    # (not a mechanical merge) — requirement stays authoritative, coverage stays intact.
    research_ctx = (
        _research_context(requirement, spec_dir, backend, model, research_budget,
                          research_top)
        if research and not use_spec else None
    )
    spec, acc = extract_spec(
        requirement, spec_dir,
        expected="\n\n".join(x for x in (expected, answered) if x) or None,
        research=research_ctx,
        backend=backend, model=model, max_iters=spec_iters, reuse=use_spec,
    )
    print(f"[area]        spec OK: {len(spec.features)} features, {len(acc.criteria)} AC")
    # Deliberately NOT gated on `clarify`. It used to be `clarify and spec_review`,
    # which meant --no-clarify silently switched OFF the independent reviewer as a
    # side effect — and --no-clarify is exactly what you pass for an UNATTENDED run,
    # so the review was disabled precisely when nobody was watching. Its findings are
    # still worth having with clarify off: they land in assumptions.yaml, which
    # `area/reality.py` prints after the build and `provenance._MATERIALS` attests.
    # `clarify` controls whether the build STOPS; `spec_review` controls whether the
    # reviewer RUNS. Opt out of the reviewer with --no-spec-review.
    # Not on a --use-spec resume: the reviewer mutates assumptions.yaml, which is
    # in spec_digest, which the clarify confirmation is anchored on — re-reviewing
    # a reused (confirmed) spec would void that confirmation and re-wall the gate.
    if spec_review and not use_spec:
        _spec_review_step(root, name, requirement, backend, model)
    qs = _clarify_gate(root, name, clarify)
    if qs:
        return _clarify_result(name, spec, acc, root, qs)
    _maybe_design(name, backend, model, design, spec)
    return _build(name, spec, acc, root, target, backend, model, build_iters, tdd=tdd,
                  strict=strict)


def _prior_spec_text(root: Path, name: str) -> str:
    """The existing app's spec + acceptance as plain text (the current oracle),
    fed back in as context when iterating. Empty if the app has no spec yet."""
    sd = root / "specs" / safe_name(name)
    chunks = []
    for fn in ("spec.yaml", "acceptance.yaml"):
        p = sd / fn
        if p.exists():
            chunks.append(f"# {fn}\n{p.read_text(errors='ignore').strip()}")
    return "\n\n".join(chunks)


def _detect_iterate_target(app_dir: Path) -> str:
    """Build target for an iteration: match the existing app (cloudflare|plain)."""
    try:
        from area.deploy import detect_provider

        return "cloudflare" if detect_provider(app_dir) == "cloudflare" else "plain"
    except Exception:  # noqa: BLE001
        return "cloudflare"


def compose_amended_requirement(prior_spec: str, change_request: str) -> str:
    """Fold a natural-language change request INTO the current spec so it re-enters
    the spec stage as a requirement — the request never goes raw to the build agent.
    This is what keeps the oracle-loop spine: the box edits the SPEC, not the code."""
    cr = (change_request or "").strip()
    if not prior_spec.strip():
        return cr
    return (
        "You are ITERATING on an existing app. Its CURRENT specification (the behavior "
        "already shipped and asserted by its acceptance tests) is given first. Produce an "
        "UPDATED spec that keeps all current behavior and acceptance criteria EXCEPT where "
        "the change request below modifies them; do not silently drop existing criteria.\n\n"
        "=== CURRENT SPEC (keep unless the change overrides it) ===\n"
        f"{prior_spec}\n\n"
        "=== CHANGE REQUEST (apply on top of the current spec) ===\n"
        f"{cr}"
    )


def iterate_pipeline(
    name: str,
    change_request: str,
    *,
    target: Optional[str] = None,
    backend: Backend = "acp",
    model: Optional[str] = None,
    spec_iters: int = 3,
    build_iters: int = 3,
    design: Optional[bool] = None,
    tdd: bool = True,
    expected: Optional[str] = None,
    clarify: bool = True,
    spec_review: bool = False,
    workspace: Optional[str | Path] = None,
    strict: bool = False,
    use_spec: bool = False,
) -> PipelineResult:
    """Flow A⁺ — the "command box": amend an EXISTING app from a natural-language
    change request. The request is folded into the current spec (not handed raw to
    the agent), the oracle is re-locked (TDD on by default), and the app is rebuilt
    to green. Governed, not free-form: same spec→lock→build→gate spine as `run`.
    """
    name = safe_name(name)
    root = Path(workspace) if workspace else WORKSPACE
    prior = _prior_spec_text(root, name)
    if target is None:
        target = _detect_iterate_target(root / "apps" / name)
    amended = compose_amended_requirement(prior, change_request)
    print(f"[area] iterate: {name} ← {change_request!r}")
    return run_pipeline(
        amended, name=name, target=target, backend=backend, model=model,
        spec_iters=spec_iters, build_iters=build_iters, design=design, tdd=tdd,
        expected=expected, clarify=clarify, spec_review=spec_review, workspace=root,
        strict=strict, use_spec=use_spec,
    )


def intake_pipeline(
    artifacts: str,
    *,
    name: str = "intake",
    target: str = "cloudflare",
    backend: Backend = "acp",
    model: Optional[str] = None,
    spec_iters: int = 3,
    build_iters: int = 3,
    design: Optional[bool] = None,
    tdd: bool = False,
    expected: Optional[str] = None,
    clarify: bool = True,
    spec_review: bool = False,
    workspace: Optional[str | Path] = None,
    strict: bool = False,
    use_spec: bool = False,
) -> PipelineResult:
    """Hybrid seam: ingest AI-DLC Inception artifacts -> spec -> [design] -> build.

    AI-DLC's Testing Posture becomes acceptance criteria, so `--tdd` locks those
    as the build oracle. Construction evidence is emitted back to the AI-DLC
    trail (aidlc_trace.jsonl) for end-to-end audit.
    """
    from area.intake import emit_evidence, spec_from_aidlc

    name = safe_name(name)
    obs.set_app(name)  # scope this build's cost to this app (cost gate)
    root = Path(workspace) if workspace else WORKSPACE
    spec_dir = root / "specs" / name
    # Continue the Inception run's trace when these artifacts came from `area
    # inception` (its origin trace lives under specs/<name>/inception/), so the
    # whole chain Inception → intake → gates → deploy is ONE correlated trace.
    from area.evidence import current_trace

    trace_id = current_trace(name)
    print(f"[area] intake : {artifacts!r} (AI-DLC, trace={trace_id})")
    spec, acc = spec_from_aidlc(
        artifacts, spec_dir, expected=expected, backend=backend, model=model,
        max_iters=spec_iters, trace_id=trace_id, reuse=use_spec,
    )
    print(f"[area]        spec OK: {len(spec.features)} features, {len(acc.criteria)} AC")
    # Not on a --use-spec resume: the reviewer mutates assumptions.yaml, which is
    # in spec_digest, which the clarify confirmation is anchored on — re-reviewing
    # a reused (confirmed) spec would void that confirmation and re-wall the gate.
    if spec_review and not use_spec:
        _spec_review_step(root, name, artifacts, backend, model)
    qs = _clarify_gate(root, name, clarify)
    if qs:
        emit_evidence(spec_dir, trace_id, "clarify.needed", {"questions": len(qs)})
        return _clarify_result(name, spec, acc, root, qs)
    _maybe_design(name, backend, model, design, spec)
    res = _build(name, spec, acc, root, target, backend, model, build_iters,
                  tdd=tdd, strict=strict)
    emit_evidence(spec_dir, trace_id, "construction.done", {"passed": res.passed})
    return res


def _resolve_clone_reference(source: str, spec_dir: Path) -> str:
    """What the parity verifier should look at: the RE stage may have cloned the
    source into <spec_dir>/_sample; point there if present, else the raw source."""
    sample = spec_dir / "_sample"
    return f"{source} (local copy at: {sample})" if sample.exists() else source


def _safe_clone_source(src: str) -> bool:
    """Reject git transport-helper syntax (`ext::`, `fd::`, `<word>::…`, which run
    an arbitrary command when git touches the remote) and leading-dash option
    injection, BEFORE the agent git-clones the source. Allows local paths,
    http(s)/ssh/git URLs, and scp-like `git@host:path`."""
    s = (src or "").strip()
    if not s or s.startswith("-"):
        return False
    return re.match(r"^[A-Za-z0-9][\w.+-]*::", s) is None


def clone_pipeline(
    source: str,
    *,
    name: str = "clone",
    kind: str = "auto",
    use_rea: bool = False,
    target: str = "cloudflare",
    backend: Backend = "acp",
    model: Optional[str] = None,
    spec_iters: int = 3,
    build_iters: int = 3,
    design: Optional[bool] = None,
    tdd: bool = False,
    expected: Optional[str] = None,
    clarify: bool = True,
    spec_review: bool = False,
    workspace: Optional[str | Path] = None,
    strict: bool = False,
    use_spec: bool = False,
) -> PipelineResult:
    """Flow B: reverse-engineer a sample app -> spec -> [independent review] -> build."""
    name = safe_name(name)
    obs.set_app(name)  # scope this build's cost to this app (cost gate)
    if not _safe_clone_source(source):
        raise RuntimeError(
            f"refusing clone source {source!r}: it looks like a git transport "
            "helper (ext::/fd::/<helper>::) or option injection, which executes "
            "arbitrary commands when git touches the remote. Use a plain "
            "http(s)/ssh/git URL or a local path."
        )
    root = Path(workspace) if workspace else WORKSPACE
    print(f"[area] re-spec: {source!r} (kind={kind}, rea={use_rea})")
    spec, acc = spec_from_source(
        source, root / "specs" / name, kind=kind, use_rea=use_rea, reuse=use_spec,
        expected=expected, backend=backend, model=model, max_iters=spec_iters,
        strict=strict,
    )
    print(f"[area]        spec OK: {len(spec.features)} features, {len(acc.criteria)} AC")
    # The reference is UNTRUSTED code. Report any credential sitting in it — a token in
    # an unrelated file is how the PocketOS incident started — but do NOT rewrite
    # `_sample/`: it is the evidence this clone was reverse-engineered from, and the
    # derived copies that actually reach the build agent are redacted instead
    # (area.re.ui_capture, area.build.ui_vendor).
    sample = root / "specs" / name / "_sample"
    if sample.is_dir():
        from area import screen

        sample_hits = screen.scan_tree(sample)
        print(screen.format_report(sample_hits, what=f"the reference in {sample.name}/"))
        if sample_hits:
            print("[area]        ^ left as-is (evidence); the copies the builder reads "
                  "are redacted")

    # Capture the reference's UI as EVIDENCE (markup/CSS/tokens/assets) so the build
    # can vendor the real look instead of re-inventing it from prose. Best-effort.
    from area.re.ui_capture import capture_ui_evidence

    spec.ui = capture_ui_evidence(source, kind, root / "specs" / name)
    if spec.ui.captured:
        print(f"[area]        ui-capture: {len(spec.ui.styles)} css, "
              f"{len(spec.ui.assets)} asset(s), {len(spec.ui.rendered)} markup"
              + (" — SPA (partial)" if spec.ui.spa_caveat else ""))
    else:
        print(f"[area]        ui-capture: none ({spec.ui.notes})")
    ui_dir = spec.ui.dir if spec.ui.captured else None
    # Not on a --use-spec resume: the reviewer mutates assumptions.yaml, which is
    # in spec_digest, which the clarify confirmation is anchored on — re-reviewing
    # a reused (confirmed) spec would void that confirmation and re-wall the gate.
    if spec_review and not use_spec:
        _spec_review_step(root, name, source, backend, model)
    qs = _clarify_gate(root, name, clarify)
    if qs:
        return _clarify_result(name, spec, acc, root, qs)
    _maybe_design(name, backend, model, design, spec)
    # TDD clone: author tests for behavioral PARITY with the reference app.
    reference = _resolve_clone_reference(source, root / "specs" / name) if tdd else None
    return _build(
        name, spec, acc, root, target, backend, model, build_iters, tdd=tdd,
        reference=reference, ui_dir=ui_dir, strict=strict,
    )
