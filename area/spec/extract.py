"""Spec stage: natural-language requirement -> validated spec artifact.

Flow A intake. (Flow B feeds reverse-engineer output in as the `requirement`.)
Uses the keyless engine loop: the agent writes spec.yaml + acceptance.yaml, and
a Pydantic validator is the oracle — invalid output loops back for a fix.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from area.engine import VerifyResult, build_agent, run_until
from area.spec.models import (
    Acceptance,
    Spec,
    load_acceptance,
    load_spec,
    validate_cross,
)

_SCHEMA_GUIDE = """\
Write EXACTLY two YAML files in the current working directory, nothing else:

1) spec.yaml
   name: <short app name>
   summary: <one or two sentences>
   stack: nextjs
   entities:              # data model (may be empty list [])
     - name: <Entity>
       fields:
         - {name: <field>, type: <string|text|int|float|bool|datetime|enum>, required: <true|false>}
   features:              # at least one
     - id: <kebab-case-id>
       title: <short>
       description: <what the user can do>

2) acceptance.yaml
   criteria:              # at least one; EVERY feature id must be covered
     - id: AC-1
       feature: <must match a spec.yaml feature id>
       given: <starting state>
       when: <user action>
       then: <observable, testable result>

Rules: valid YAML only; every acceptance `feature` must match a feature `id` in
spec.yaml; every feature must have >=1 acceptance criterion; keep it minimal and
faithful to the requirement — do not invent scope.
"""


def _spec_verifier(out: Path):
    def _run() -> VerifyResult:
        problems: list[str] = []
        try:
            spec = load_spec(out / "spec.yaml")
        except Exception as e:  # missing / invalid yaml / schema mismatch
            return VerifyResult(False, f"spec.yaml invalid: {e}")
        try:
            acc = load_acceptance(out / "acceptance.yaml")
        except Exception as e:
            return VerifyResult(False, f"acceptance.yaml invalid: {e}")
        problems = validate_cross(spec, acc)
        return VerifyResult(not problems, "\n".join(problems))

    return _run


def extract_spec(
    requirement: str,
    out_dir: str | Path,
    *,
    backend: str = "acp",
    model: Optional[str] = None,
    max_iters: int = 3,
) -> tuple[Spec, Acceptance]:
    """Turn a natural-language requirement into a validated spec artifact.

    Writes <out_dir>/spec.yaml and <out_dir>/acceptance.yaml. Returns the parsed
    (Spec, Acceptance). Raises RuntimeError if it cannot be made valid.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    task = (
        "You are the spec stage of a software factory. Turn the REQUIREMENT "
        "below into a structured spec.\n\n"
        f"=== REQUIREMENT ===\n{requirement}\n\n"
        f"=== OUTPUT FORMAT ===\n{_SCHEMA_GUIDE}"
    )

    agent = build_agent(backend, model=model)
    try:
        passed, _ = run_until(
            agent, out, task, _spec_verifier(out), max_iters=max_iters
        )
    finally:
        agent.close()

    if not passed:
        raise RuntimeError(
            f"spec did not validate after {max_iters} attempts; inspect "
            f"{out / 'spec.yaml'} and {out / 'acceptance.yaml'}"
        )

    return load_spec(out / "spec.yaml"), load_acceptance(out / "acceptance.yaml")
