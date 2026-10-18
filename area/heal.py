"""area.heal — Specora-inspired healer: fix a built app at the SPEC level.

A runtime error is addressed by editing the spec (spec.yaml / acceptance.yaml),
not by patching generated code; then the app is regenerated from the healed
spec. "Bugs are fixed at the specification level, not in generated code."
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from area._util import safe_name
from area.build import build_app
from area.engine import build_agent, run_until
from area.pipeline import WORKSPACE
from area.spec.extract import _SCHEMA_GUIDE, _spec_verifier
from area.spec.models import Acceptance, Spec, load_acceptance, load_spec


@dataclass
class HealResult:
    name: str
    spec_changed: bool
    rebuilt: bool
    build_passed: Optional[bool]
    spec: Spec
    acceptance: Acceptance


def heal(
    name: str,
    error: str,
    *,
    target: str = "cloudflare",
    backend: str = "acp",
    model: Optional[str] = None,
    spec_iters: int = 3,
    rebuild: bool = True,
    build_iters: int = 3,
    workspace: Optional[str | Path] = None,
) -> HealResult:
    """Heal an app from a runtime error by fixing its spec, then regenerate."""
    root = Path(workspace) if workspace else WORKSPACE
    name = safe_name(name)
    spec_dir = root / "specs" / name
    app_dir = root / "apps" / name
    spec_path = spec_dir / "spec.yaml"
    if not spec_path.exists():
        raise RuntimeError(f"no spec at {spec_path} — nothing to heal")
    before = spec_path.read_text()

    task = (
        "You are the HEALER of a software factory. A deployed app hit a runtime "
        "error. Fix it AT THE SPEC LEVEL — edit spec.yaml and/or acceptance.yaml "
        "in the working directory — NOT by patching generated code.\n\n"
        f"=== RUNTIME ERROR / SYMPTOM ===\n{error}\n\n"
        "Read the current spec.yaml and acceptance.yaml, make the MINIMAL change "
        "that addresses the error at the specification level (a missing field or "
        "wrong type, a missing validation, or a missing/weak acceptance criterion "
        "that would have caught it), and rewrite the two files. Add an acceptance "
        "criterion that encodes the fix so the build loop verifies it.\n\n"
        f"=== OUTPUT FORMAT (keep valid) ===\n{_SCHEMA_GUIDE}"
    )

    agent = build_agent(backend, model=model)
    try:
        ok, _ = run_until(
            agent, spec_dir, task, _spec_verifier(spec_dir), max_iters=spec_iters
        )
    finally:
        agent.close()
    if not ok:
        raise RuntimeError(f"healed spec did not validate; inspect {spec_dir}")

    spec = load_spec(spec_path)
    acc = load_acceptance(spec_dir / "acceptance.yaml")
    changed = spec_path.read_text() != before

    build_passed = None
    if rebuild:
        print(f"[area] heal: regenerating {app_dir} from healed spec (target={target})")
        build_passed = build_app(
            spec, acc, app_dir, target=target, backend=backend, model=model,
            max_iters=build_iters,
        )
        print(f"[area] heal: rebuild {'GREEN' if build_passed else 'NOT green'}")

    return HealResult(name, changed, rebuild, build_passed, spec, acc)
