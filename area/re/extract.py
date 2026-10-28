"""Flow B: reverse-engineer a sample app -> spec artifact (keyless).

Tier 1 (default) uses the agent's built-in tools only (clone/read source, curl a
URL) — no REA, no browser sandbox. Good for open-source repos, your own code,
simple/SSR sites.

Tier 2 (use_rea=True, opt-in) additionally wires the REA MCP server into the
agent (deep reverse-engineering of binaries / closed-source). REA is beta and
legally sensitive.

Output is the SAME spec schema as area.spec, so a reverse-engineered app flows
into the exact same build + deploy pipeline.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from area.engine import Backend, build_agent, run_until
from area.spec.extract import _SCHEMA_GUIDE, _spec_verifier, expected_block
from area.spec.models import Acceptance, Spec, load_acceptance, load_spec


def rea_mcp_config() -> dict[str, Any]:
    """REA MCP server (stdio via npx) for Tier 2 reverse-engineering."""
    from area.engine import mcp_stdio_server

    return {
        # `--mcp` makes rea-agents speak MCP on stdio; bare `rea` just prints help
        # and exits, so the client sees the connection close. The clean npm cache
        # dodges the root-owned ~/.npm EACCES crash on first launch. PIN the exact
        # version: `-y rea-agents` would auto-install whatever latest resolves
        # (supply-chain risk + it ships breaking changes across minors).
        "rea": mcp_stdio_server(
            command="npx",
            args=["-y", "rea-agents@6.7.0", "--mcp"],
            env={"npm_config_cache": str(Path.home() / ".cache" / "npm-area")},
            description="Reverse Engineer Anything",
        )
    }



# A local-path reference was the one kind that never reached `_sample/`: the RE prompt
# told the agent "local path -> read the files there", so nothing was isolated. Two
# consequences, both silent:
#
#  1. `capture_ui_evidence` looks for `_sample/` (or an http source) and otherwise
#     returns "no _sample/ tree" — so a local-path clone captured NO UI evidence, which
#     means `_with_ui_parity` had nothing to bolt onto the build oracle and the visual
#     gate was never auto-selected. The UI half of Flow B did nothing, and the build
#     still went green. `area clone ./some-app` is the most natural invocation there is.
#  2. `.claude/skills/clone-from-source` requires the reference to be ISOLATED and READ,
#     never run. Reading the user's live directory in place is not that.
#
# The intent was always otherwise: ui_capture's own docstring says "_sample/ tree
# (repo/local-path reference cloned by RE)". This makes the path kind match it.
#
# Generated trees are skipped, which is also what makes it affordable: the AREA-built
# apps on this machine are 1.2-1.4 GB, almost all of it node_modules and .next.
def isolate_local_path(source: str, out_dir: Path) -> tuple[int, int]:
    """Copy a local reference into `<out_dir>/_sample/`. Returns (files, bytes).

    Idempotent: an existing non-empty `_sample/` is left alone, so a re-run does not
    silently replace the evidence an earlier spec was derived from.
    """
    import shutil

    from area.paths import GENERATED_AT_ROOT, GENERATED_DIRS

    src = Path(source).expanduser()
    sample = out_dir / "_sample"
    if sample.is_dir() and any(sample.iterdir()):
        return (0, 0)
    if not src.is_dir():
        return (0, 0)

    skip = set(GENERATED_DIRS)
    n = total = 0
    for p in src.rglob("*"):
        rel = p.relative_to(src)
        if any(part in skip for part in rel.parts):
            continue
        if rel.parts and rel.parts[0] in GENERATED_AT_ROOT:
            continue
        if not p.is_file() or p.is_symlink():
            continue
        dst = sample / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(p, dst)
        except OSError:
            continue
        n += 1
        total += dst.stat().st_size
    return (n, total)

def spec_from_source(
    source: str,
    out_dir: str | Path,
    *,
    kind: str = "auto",
    use_rea: bool = False,
    expected: Optional[str] = None,
    backend: Backend = "acp",
    model: Optional[str] = None,
    max_iters: int = 3,
    reuse: bool = False,
    strict: bool = False,
) -> tuple[Spec, Acceptance]:
    """Reverse-engineer a sample app into a validated spec artifact.

    `source` is a git URL, a local path, or an http(s) URL. `kind` in
    {auto, repo, path, url}. `use_rea` enables Tier 2 (REA MCP).
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    if reuse:
        sp, ac = out / "spec.yaml", out / "acceptance.yaml"
        if not (sp.exists() and ac.exists()):
            raise RuntimeError(
                f"--use-spec: no re-spec to reuse at {out}. Run without it first.")
        print(f"[area] re-spec: reusing {sp} (not re-investigating the reference)")
        return load_spec(sp), load_acceptance(ac)

    # B4: for a LOCAL path the reference is already on disk; isolate it into _sample/
    # (byte-exact evidence) then hand the agent a credential-REDACTED copy (_sample_safe/),
    # so a token in the reference never enters the agent's context. git/URL kinds are
    # still fetched by the agent (closing those needs the pipeline to do the fetch — a
    # funded live run; the B4 residual).
    agent_ref = "_sample"
    if kind in ("path", "auto") and Path(source).expanduser().is_dir():
        files, size = isolate_local_path(source, out)
        if files:
            print(f"[area] re-spec: isolated {files} file(s) ({size / 1e6:.1f} MB) "
                  f"into {out / '_sample'} (generated trees skipped)")
        sample = out / "_sample"
        if sample.is_dir():
            import shutil

            from area import screen

            safe = out / "_sample_safe"
            if safe.is_dir():
                shutil.rmtree(safe)
            hits = screen.redact_tree(sample, safe)
            if hits:
                print(f"[area] re-spec: {len(hits)} credential-shaped value(s) in the "
                      "reference — the agent reads a redacted copy (_sample_safe/); "
                      "_sample/ kept byte-exact for provenance")
                if strict:
                    raise RuntimeError(
                        f"--strict: refusing — {len(hits)} credential finding(s) in the "
                        "reference _sample/. Re-run without --strict to build against the "
                        "redacted copy.")
            agent_ref = "_sample_safe"

    tier2 = (
        "\nYou ALSO have the REA toolset (MCP) available for deep reverse-"
        "engineering (binaries, .NET, APK, native). Use it when the source tools "
        "are not enough."
        if use_rea else ""
    )
    if agent_ref == "_sample_safe":
        investigate = (
            f"The LOCAL reference is already isolated and credential-redacted at "
            f"./{agent_ref} (generated trees skipped). Read it THERE; never run it, "
            f"never `npm install`, never fetch over the network."
        )
    else:
        investigate = (
            "Investigate with your own tools (keyless):\n"
            "- git URL  -> `git clone` into ./_sample and read the source.\n"
            "- local path -> ALREADY ISOLATED at ./_sample (generated trees "
            "skipped). Read it there; never run it, never `npm install`.\n"
            "- http(s) URL -> `curl` it and inspect the HTML / visible behavior."
        )
    task = (
        "You are the reverse-engineer stage of a software factory. "
        "Investigate the SAMPLE APP below and produce a faithful RE-SPEC so we "
        "can build a clone of its features.\n\n"
        f"=== SAMPLE APP (kind={kind}) ===\n{source}\n\n"
        f"{investigate}"
        f"{tier2}\n"
        "Work out the app's observable FEATURES and DATA MODEL. Capture ONLY what "
        "you can evidence; do not invent scope. Target stack for the clone is "
        "Next.js, so describe features in a framework-neutral way.\n\n"
        "ROUTES ARE NOT OPTIONAL HERE. Enumerate the paths the reference actually "
        "serves and put them in `spec.routes` — for a Next.js app they are visible in "
        "its app/ or pages/ tree, so this is discovery, not invention. Then QUOTE the "
        "literal path in every acceptance criterion that visits, requests or redirects "
        "to one. A clone must serve the SAME paths as its reference: a holdout author "
        "is given acceptance.yaml alone and never sees spec.yaml, so a path you leave "
        "unwritten is a path it invents, and the frozen oracle will then assert "
        "parity against a URL neither app serves.\n\n"
        f"{expected_block(expected)}=== OUTPUT FORMAT ===\n{_SCHEMA_GUIDE}"
    )

    mcp = rea_mcp_config() if use_rea else None
    agent = build_agent(backend, model=model, mcp_config=mcp)
    try:
        passed, _ = run_until(
            agent, out, task, _spec_verifier(out), max_iters=max_iters, label="re"
        )
    finally:
        agent.close()

    if not passed:
        raise RuntimeError(
            f"re-spec did not validate after {max_iters} attempts; inspect {out}"
        )
    return load_spec(out / "spec.yaml"), load_acceptance(out / "acceptance.yaml")
