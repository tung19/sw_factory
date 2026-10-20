"""Spec stage: natural-language requirement -> validated spec artifact.

Flow A intake. (Flow B feeds reverse-engineer output in as the `requirement`.)
Uses the keyless engine loop: the agent writes spec.yaml + acceptance.yaml, and
a Pydantic validator is the oracle — invalid output loops back for a fix.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from area.engine import VerifyResult, build_agent, run_until
from area.spec.models import (
    Acceptance,
    Spec,
    load_acceptance,
    load_spec,
    validate_cross,
)

_SCHEMA_GUIDE = """\
Write these YAML files in the current working directory, nothing else:

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

3) assumptions.yaml       # the requirement is rarely complete — record your guesses
   assumptions:           # every ambiguous point where you chose a default
     - question: <what the requirement left unclear>
       assumption: <the default you decided to go with>
       material: <true if a wrong guess here would significantly change the app>
   # write `assumptions: []` ONLY if the requirement was genuinely unambiguous.

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


def expected_block(expected: Optional[str]) -> str:
    """Prompt block for user-provided EXPECTED RESULTS — authoritative examples
    that become acceptance criteria (the user is handing us part of the oracle)."""
    if not expected or not expected.strip():
        return ""
    return (
        "\n=== EXPECTED RESULTS (AUTHORITATIVE — from the user) ===\n"
        "Concrete examples of correct behavior. Turn EACH into a precise "
        "acceptance criterion the app MUST satisfy — these are ground truth: do "
        "NOT weaken, merge away, or drop them.\n"
        f"{expected.strip()}\n"
    )


def load_assumptions(out_dir: str | Path) -> list[dict]:
    """Read the spec stage's assumptions ledger (empty if none/invalid)."""
    p = Path(out_dir) / "assumptions.yaml"
    if not p.exists():
        return []
    try:
        data = yaml.safe_load(p.read_text()) or {}
        items = data.get("assumptions", []) if isinstance(data, dict) else []
        return [a for a in items if isinstance(a, dict) and a.get("question")]
    except Exception:
        return []


def append_assumptions(out_dir: str | Path, items: list[dict]) -> int:
    """Merge extra assumption dicts into the ledger (dedup by question text).

    Used by the independent spec reviewer to fold the ambiguities it found into the
    same assumptions.yaml the --clarify gate reads. Returns how many were newly added.
    """
    if not items:
        return 0
    p = Path(out_dir) / "assumptions.yaml"
    existing = load_assumptions(out_dir)
    seen = {str(a.get("question", "")).strip().lower() for a in existing}
    added = [a for a in items
             if str(a.get("question", "")).strip()
             and str(a.get("question", "")).strip().lower() not in seen]
    if not added:
        return 0
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump({"assumptions": existing + added}, sort_keys=False,
                                allow_unicode=True))
    return len(added)


def extract_spec(
    requirement: str,
    out_dir: str | Path,
    *,
    expected: Optional[str] = None,
    backend: str = "acp",
    model: Optional[str] = None,
    max_iters: int = 3,
) -> tuple[Spec, Acceptance]:
    """Turn a natural-language requirement into a validated spec artifact.

    Writes <out_dir>/spec.yaml, acceptance.yaml, assumptions.yaml. Returns the
    parsed (Spec, Acceptance). `expected` carries user-provided expected-result
    examples that become authoritative acceptance criteria.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    task = (
        "You are the spec stage of a software factory. Turn the REQUIREMENT "
        "below into a structured spec.\n\n"
        f"=== REQUIREMENT ===\n{requirement}\n"
        f"{expected_block(expected)}\n"
        f"=== OUTPUT FORMAT ===\n{_SCHEMA_GUIDE}"
    )

    agent = build_agent(backend, model=model)
    try:
        passed, _ = run_until(
            agent, out, task, _spec_verifier(out), max_iters=max_iters, label="spec"
        )
    finally:
        agent.close()

    if not passed:
        raise RuntimeError(
            f"spec did not validate after {max_iters} attempts; inspect "
            f"{out / 'spec.yaml'} and {out / 'acceptance.yaml'}"
        )

    return load_spec(out / "spec.yaml"), load_acceptance(out / "acceptance.yaml")
