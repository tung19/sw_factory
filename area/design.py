"""area.design — MetaGPT-style ARCHITECT stage: spec -> system design (design.md).

Borrows MetaGPT's "design before code" pattern (not its code): a separate agent
turns the spec into a concise, implementable system design that the build stage
then follows. Keeps each role a distinct OpenHands agent + an artifact.
"""
from __future__ import annotations

from typing import Optional

from area._util import safe_name
from area.engine import Backend, build_agent, run_once
from area.pipeline import WORKSPACE


def design_stage(
    name: str, *, backend: Backend = "acp", model: Optional[str] = None
) -> str:
    """Write <spec_dir>/design.md from the spec. Returns the design text."""
    name = safe_name(name)
    spec_dir = WORKSPACE / "specs" / name
    if not (spec_dir / "spec.yaml").exists():
        raise RuntimeError(f"no spec at {spec_dir}")
    spec_yaml = (spec_dir / "spec.yaml").read_text()
    acc_path = spec_dir / "acceptance.yaml"
    acc_yaml = acc_path.read_text() if acc_path.exists() else ""

    task = (
        "You are the ARCHITECT stage of a software factory (design BEFORE code). "
        "From the spec below, write a concise system design to `design.md` in the "
        "working directory:\n"
        "1. components & responsibilities\n"
        "2. data model\n"
        "3. routes/pages and the Server Actions\n"
        "4. a file plan (exact paths to create)\n"
        "5. key decisions & risks\n"
        "Keep it tight and directly implementable for a Next.js app. Write ONLY "
        "design.md.\n\n"
        f"=== spec.yaml ===\n{spec_yaml}\n=== acceptance.yaml ===\n{acc_yaml}"
    )
    agent = build_agent(backend, model=model)
    try:
        run_once(agent, spec_dir, task, label="design")
    finally:
        agent.close()
    dp = spec_dir / "design.md"
    return dp.read_text() if dp.exists() else ""
