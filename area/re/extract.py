"""Flow B: reverse-engineer a sample app -> spec artifact (keyless).

Tier 1 (default) uses the agent's built-in tools only (clone/read source, curl a
URL) — no REA, no browser sandbox. Good for open-source repos, your own code,
simple/SSR sites.

Tier 2 (use_rea=True, opt-in) additionally wires the REA MCP server into the
agent (deep reverse-engineering of binaries / closed-source). REA is beta and
legally sensitive — use ONLY on software you are authorized to analyze.

Output is the SAME spec schema as area.spec, so a reverse-engineered app flows
into the exact same build + deploy pipeline.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from area.engine import build_agent, run_until
from area.spec.extract import _SCHEMA_GUIDE, _spec_verifier
from area.spec.models import Acceptance, Spec, load_acceptance, load_spec


def rea_mcp_config() -> dict:
    """REA MCP server (stdio via npx) for Tier 2 reverse-engineering."""
    from openhands.sdk.mcp.config import MCPServer

    return {
        "rea": MCPServer(
            transport="stdio",
            command="npx",
            args=["-y", "rea-agents"],
            description="Reverse Engineer Anything (authorized targets only)",
        )
    }


def spec_from_source(
    source: str,
    out_dir: str | Path,
    *,
    kind: str = "auto",
    use_rea: bool = False,
    backend: str = "acp",
    model: Optional[str] = None,
    max_iters: int = 3,
) -> tuple[Spec, Acceptance]:
    """Reverse-engineer a sample app into a validated spec artifact.

    `source` is a git URL, a local path, or an http(s) URL. `kind` in
    {auto, repo, path, url}. `use_rea` enables Tier 2 (REA MCP).
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    tier2 = (
        "\nYou ALSO have the REA toolset (MCP) available for deep reverse-"
        "engineering (binaries, .NET, APK, native). Use it when the source tools "
        "are not enough. Only analyze software the user is authorized to."
        if use_rea else ""
    )
    task = (
        "You are the reverse-engineer stage of a software factory. "
        "Investigate the SAMPLE APP below and produce a faithful RE-SPEC so we "
        "can build a clone of its features.\n\n"
        f"=== SAMPLE APP (kind={kind}) ===\n{source}\n\n"
        "Investigate with your own tools (keyless):\n"
        "- git URL  -> `git clone` into ./_sample and read the source.\n"
        "- local path -> read the files there.\n"
        "- http(s) URL -> `curl` it and inspect the HTML / visible behavior."
        f"{tier2}\n"
        "Work out the app's observable FEATURES and DATA MODEL. Capture ONLY what "
        "you can evidence; do not invent scope. Target stack for the clone is "
        "Next.js, so describe features in a framework-neutral way.\n\n"
        f"=== OUTPUT FORMAT ===\n{_SCHEMA_GUIDE}"
    )

    mcp = rea_mcp_config() if use_rea else None
    agent = build_agent(backend, model=model, mcp_config=mcp)
    try:
        passed, _ = run_until(agent, out, task, _spec_verifier(out), max_iters=max_iters)
    finally:
        agent.close()

    if not passed:
        raise RuntimeError(
            f"re-spec did not validate after {max_iters} attempts; inspect {out}"
        )
    return load_spec(out / "spec.yaml"), load_acceptance(out / "acceptance.yaml")
