"""area.inception.engine — the governed Inception bolts (PR8 Phase 1).

Each bolt: the AI PROPOSES the artifact file, the human DISPOSES (the approve
callback: accept / edit / regenerate), then the approved text is written and an
evidence record emitted. Both the propose and approve steps are INJECTABLE, so
the orchestration is tested without an agent or a human; the defaults run the
real agent and (in the CLI) prompt the human.

Output = the four files of docs/aidlc-artifact-contract.md, ready for
area.intake.aidlc. The human shaping the Testing Posture here is literally
shaping the oracle — AREA's spine ("is the oracle correct?" is the human's gate).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from area.engine import build_agent, run_once
from area.intake.aidlc import emit_evidence, new_trace_id

# Signal an approve callback can return to re-run a bolt (regenerate).
REGENERATE = object()

MAX_REGEN = 3


@dataclass(frozen=True)
class Bolt:
    key: str
    filename: str
    title: str
    instruction: str


BOLTS: tuple[Bolt, ...] = (
    Bolt(
        "intent", "01-intent.md", "Intent",
        "Write 01-intent.md: the Problem, Goals, Constraints, and an OPTIONAL Data "
        "model (entities + fields as `name (type, required)`). Capture only what "
        "the requirement implies — invent no scope.",
    ),
    Bolt(
        "stories", "02-user-stories.md", "User Stories",
        "Write 02-user-stories.md: one bullet per story, "
        "`- **US-N**: As a <role>, I want <capability>, so that <value>.` Cover the "
        "capabilities the requirement implies; do not invent new scope.",
    ),
    Bolt(
        "units", "03-units-of-work.md", "Units of Work",
        "Write 03-units-of-work.md: Units of Work, each a SINGLE buildable feature, "
        "`- **UoW-N — <kebab-id>**: <one-line description>. (covers US-x)`. One UoW "
        "per feature; stay within the user stories.",
    ),
    Bolt(
        "posture", "04-testing-posture.md", "Testing Posture",
        "Write 04-testing-posture.md: for EACH UoW in 03-units-of-work.md, one or "
        "more acceptance statements `- UoW-N: Given <state>, When <action>, Then "
        "<observable result>.` EVERY UoW must have at least one statement. These are "
        "the ORACLE — make them concrete, observable, and testable.",
    ),
)

# Propose/approve callback types.
ProposeFn = Callable[[Bolt, str], str]
ApproveFn = Callable[[Bolt, str], object]  # returns approved str or REGENERATE


def _prior_files(out: Path, upto: Bolt) -> list[str]:
    names = []
    for b in BOLTS:
        if b.key == upto.key:
            break
        if (out / b.filename).exists():
            names.append(b.filename)
    return names


def bolt_prompt(bolt: Bolt, requirement: str, out: Path, *, regen: bool = False) -> str:
    """The agent prompt for one bolt (pure). Points at the already-approved prior
    files so each bolt builds on the last."""
    prior = _prior_files(out, bolt)
    read = (f"First READ the already-approved files here: {', '.join(prior)}. "
            if prior else "")
    again = ("Your previous draft was rejected — produce a DIFFERENT, better draft. "
             if regen else "")
    return (
        "You are the INCEPTION front-end of a software factory, at the "
        f"'{bolt.title}' bolt. Follow the AI-DLC artifact contract.\n"
        f"=== REQUIREMENT ===\n{requirement}\n\n"
        f"{again}{read}{bolt.instruction}\n"
        f"Write ONLY the file {bolt.filename} in the current directory — do not "
        "create other files, do not scaffold an app, do not explain. After "
        "writing, STOP."
    )


def _agent_propose(bolt: Bolt, prompt: str, out: Path, *, backend: str,
                   model: Optional[str]) -> str:
    """Default propose: run the agent once; it writes the bolt file; read it back."""
    agent = build_agent(backend, model=model)
    try:
        run_once(agent, out, prompt, label=f"inception:{bolt.key}")
    finally:
        agent.close()
    f = out / bolt.filename
    return f.read_text(errors="ignore") if f.exists() else ""


def validate_artifacts(out: str | Path) -> list[str]:
    """Advisory contract check: every UoW must have ≥1 Given/When/Then statement
    tagged to it. Returns a list of human-readable warnings (empty = clean)."""
    out = Path(out)
    warnings: list[str] = []
    units = (out / "03-units-of-work.md")
    posture = (out / "04-testing-posture.md")
    if not units.exists():
        return ["03-units-of-work.md is missing"]
    uow = set(re.findall(r"UoW-\d+", units.read_text(errors="ignore")))
    if not uow:
        warnings.append("no Units of Work found (expected `UoW-N` ids)")
    ptext = posture.read_text(errors="ignore") if posture.exists() else ""
    for u in sorted(uow):
        # tolerate a bold/italic id — `- **UoW-1**:` as well as `- UoW-1:`
        stmts = re.findall(rf"^-\s*\*{{0,2}}{re.escape(u)}\*{{0,2}}:.*$", ptext, re.M)
        if not stmts:
            warnings.append(f"{u} has no Given/When/Then testing-posture statement")
        elif not all(all(k in s for k in ("Given", "When", "Then")) for s in stmts):
            warnings.append(f"{u} has a testing-posture statement that is not Given/When/Then")
    return warnings


def run_inception(
    requirement: str,
    out_dir: str | Path,
    *,
    approve_fn: ApproveFn,
    propose_fn: Optional[ProposeFn] = None,
    backend: str = "acp",
    model: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> dict:
    """Run the governed Inception bolts. Returns
    {out, approved, warnings, trace_id, files}. `propose_fn(bolt, prompt)->str`
    defaults to the agent; `approve_fn(bolt, proposed)->str|REGENERATE` is the
    human-governance seam (REGENERATE re-proposes, capped at MAX_REGEN)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    trace_id = trace_id or new_trace_id()
    if propose_fn is None:
        def propose_fn(bolt: Bolt, prompt: str) -> str:  # noqa: E306
            return _agent_propose(bolt, prompt, out, backend=backend, model=model)

    emit_evidence(out, trace_id, "inception.start", {"requirement": requirement[:500]})
    approved: dict[str, str] = {}
    unapproved: list[str] = []
    for bolt in BOLTS:
        final: Optional[str] = None
        accepted = False
        for attempt in range(1, MAX_REGEN + 1):
            proposed = propose_fn(bolt, bolt_prompt(bolt, requirement, out, regen=attempt > 1))
            decision = approve_fn(bolt, proposed)
            final = proposed if decision is REGENERATE else decision  # type: ignore[assignment]
            if decision is REGENERATE:
                emit_evidence(out, trace_id, "inception.regenerate", {"bolt": bolt.key, "attempt": attempt})
                continue
            accepted = True
            break
        if not accepted:
            # The regenerate cap was hit and the human never accepted. Write the
            # last draft so the flow can continue, but do NOT record it as approved
            # — flag it loudly (this is the oracle-shaping stage).
            unapproved.append(bolt.key)
            emit_evidence(out, trace_id, "inception.regen_cap_unapproved", {"bolt": bolt.key})
            print(f"[area] ⚠ inception: '{bolt.key}' hit the regenerate cap "
                  f"({MAX_REGEN}) still rejected — writing the last draft UNAPPROVED, review it.")
        (out / bolt.filename).write_text(final or "")
        approved[bolt.key] = final or ""
        emit_evidence(out, trace_id, "inception.bolt",
                      {"bolt": bolt.key, "chars": len(final or ""), "approved": accepted})

    warnings = validate_artifacts(out)
    emit_evidence(out, trace_id, "inception.ready",
                  {"files": [b.filename for b in BOLTS], "warnings": warnings,
                   "unapproved": unapproved})
    return {
        "out": out,
        "approved": approved,
        "unapproved": unapproved,
        "warnings": warnings,
        "trace_id": trace_id,
        "files": [str(out / b.filename) for b in BOLTS],
    }
