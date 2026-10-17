"""Flow B (Tier 1): reverse-engineer a sample app -> spec artifact (keyless).

Tier 1 uses the agent's built-in tools only (clone/read source, or curl a URL) —
no REA, no browser sandbox. Good for open-source repos, your own code, and
simple/SSR sites. Deep binary / closed-source is Tier 2 (REA MCP, later phase).

The output is the SAME spec schema as area.spec, so a reverse-engineered app
flows into the exact same build + deploy pipeline. Only the intake differs:
instead of a written requirement, the agent first investigates a sample app.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from area.engine import build_agent, run_until
from area.spec.extract import _SCHEMA_GUIDE, _spec_verifier
from area.spec.models import Acceptance, Spec, load_acceptance, load_spec


def spec_from_source(
    source: str,
    out_dir: str | Path,
    *,
    kind: str = "auto",
    backend: str = "acp",
    model: Optional[str] = None,
    max_iters: int = 3,
) -> tuple[Spec, Acceptance]:
    """Reverse-engineer a sample app into a validated spec artifact.

    `source` is a git URL, a local path, or an http(s) URL. `kind` in
    {auto, repo, path, url}. Writes spec.yaml + acceptance.yaml into out_dir.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    task = (
        "You are the reverse-engineer stage (Tier 1) of a software factory. "
        "Investigate the SAMPLE APP below and produce a faithful RE-SPEC so we "
        "can build a clone of its features.\n\n"
        f"=== SAMPLE APP (kind={kind}) ===\n{source}\n\n"
        "Investigate using ONLY your own tools (keyless):\n"
        "- git URL  -> `git clone` it into a ./_sample subfolder and read the source.\n"
        "- local path -> read the files there.\n"
        "- http(s) URL -> `curl` it and inspect the HTML / visible behavior.\n"
        "Work out the app's observable FEATURES and DATA MODEL. Capture ONLY what "
        "you can evidence from the app; do not invent scope. Target stack for the "
        "clone is Next.js, so describe features in a framework-neutral way.\n\n"
        f"=== OUTPUT FORMAT ===\n{_SCHEMA_GUIDE}"
    )

    agent = build_agent(backend, model=model)
    try:
        passed, _ = run_until(agent, out, task, _spec_verifier(out), max_iters=max_iters)
    finally:
        agent.close()

    if not passed:
        raise RuntimeError(
            f"re-spec did not validate after {max_iters} attempts; inspect {out}"
        )
    return load_spec(out / "spec.yaml"), load_acceptance(out / "acceptance.yaml")
