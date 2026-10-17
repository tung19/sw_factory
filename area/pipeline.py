"""area.pipeline — Flow A end to end: requirement -> spec -> working app."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from area.build import build_app
from area.spec import Acceptance, Spec, extract_spec

_WORKSPACE = Path(__file__).resolve().parent.parent / "workspace"


@dataclass
class PipelineResult:
    name: str
    spec: Spec
    acceptance: Acceptance
    spec_dir: Path
    app_dir: Path
    passed: bool


def run_pipeline(
    requirement: str,
    *,
    name: str = "app",
    backend: str = "acp",
    model: Optional[str] = None,
    spec_iters: int = 3,
    build_iters: int = 3,
    workspace: Optional[str | Path] = None,
) -> PipelineResult:
    """Intake -> spec -> build, one call. Returns a PipelineResult."""
    root = Path(workspace) if workspace else _WORKSPACE
    spec_dir = root / "specs" / name
    app_dir = root / "apps" / name

    print(f"[area] (1/2) spec  : {requirement!r}\n[area]        -> {spec_dir}")
    spec, acc = extract_spec(
        requirement, spec_dir, backend=backend, model=model, max_iters=spec_iters
    )
    print(
        f"[area]        spec OK: {len(spec.features)} features, "
        f"{len(acc.criteria)} acceptance criteria"
    )

    print(f"[area] (2/2) build : -> {app_dir}")
    passed = build_app(
        spec, acc, app_dir, backend=backend, model=model, max_iters=build_iters
    )
    print(f"[area]        build {'GREEN' if passed else 'NOT green'}")

    return PipelineResult(name, spec, acc, spec_dir, app_dir, passed)
