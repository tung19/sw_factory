"""area.pipeline — Flow A (requirement) and Flow B (clone) end to end."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from area.build import build_app
from area.re import spec_from_source
from area.spec import Acceptance, Spec, extract_spec

WORKSPACE = Path(__file__).resolve().parent.parent / "workspace"


@dataclass
class PipelineResult:
    name: str
    spec: Spec
    acceptance: Acceptance
    spec_dir: Path
    app_dir: Path
    passed: bool


def _build(name, spec, acc, root, target, backend, model, build_iters) -> PipelineResult:
    app_dir = root / "apps" / name
    print(f"[area] build : target={target} -> {app_dir}")
    passed = build_app(
        spec, acc, app_dir, target=target, backend=backend, model=model,
        max_iters=build_iters,
    )
    print(f"[area]        build {'GREEN' if passed else 'NOT green'}")
    return PipelineResult(name, spec, acc, root / "specs" / name, app_dir, passed)


def run_pipeline(
    requirement: str,
    *,
    name: str = "app",
    target: str = "cloudflare",
    backend: str = "acp",
    model: Optional[str] = None,
    spec_iters: int = 3,
    build_iters: int = 3,
    workspace: Optional[str | Path] = None,
) -> PipelineResult:
    """Flow A: requirement -> spec -> build."""
    root = Path(workspace) if workspace else WORKSPACE
    print(f"[area] (1/2) spec  : {requirement!r}")
    spec, acc = extract_spec(
        requirement, root / "specs" / name, backend=backend, model=model,
        max_iters=spec_iters,
    )
    print(f"[area]        spec OK: {len(spec.features)} features, {len(acc.criteria)} AC")
    return _build(name, spec, acc, root, target, backend, model, build_iters)


def clone_pipeline(
    source: str,
    *,
    name: str = "clone",
    kind: str = "auto",
    use_rea: bool = False,
    target: str = "cloudflare",
    backend: str = "acp",
    model: Optional[str] = None,
    spec_iters: int = 3,
    build_iters: int = 3,
    workspace: Optional[str | Path] = None,
) -> PipelineResult:
    """Flow B: reverse-engineer a sample app -> spec -> build."""
    root = Path(workspace) if workspace else WORKSPACE
    print(f"[area] (1/2) re-spec: {source!r} (kind={kind}, rea={use_rea})")
    spec, acc = spec_from_source(
        source, root / "specs" / name, kind=kind, use_rea=use_rea,
        backend=backend, model=model, max_iters=spec_iters,
    )
    print(f"[area]        spec OK: {len(spec.features)} features, {len(acc.criteria)} AC")
    return _build(name, spec, acc, root, target, backend, model, build_iters)
