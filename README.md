# AREA

Internal AI software factory. Two entry flows, one shared pipeline:

- **Flow A — Requirement:** natural-language requirement → spec → develop → self-correcting loop → deploy.
- **Flow B — Clone:** a sample app → reverse-engineer (2 tiers) → spec → same pipeline.

**Execution core:** [OpenHands `software-agent-sdk`](https://github.com/OpenHands/software-agent-sdk) (pinned, wrapped by `area/engine`).
Full design + rationale (and why not MetaGPT / Specora / REA-as-core): see [PLAN.md](PLAN.md).

## Quickstart (local-first)

AREA runs on **your** machine with **your** accounts — your Claude, your
Cloudflare/Vercel. Nothing (code, credentials) leaves your machine. See
[docs/adr/0001](docs/adr/0001-local-first-byo-everything.md) for why.

```bash
git clone <this repo> && cd SW_Factory
bash scripts/install.sh      # venv + install + environment check
area doctor                  # re-check anytime (Python/Node/git/Claude/deploy)
area gui                     # dashboard at http://127.0.0.1:8787 (auto-opens)
```

Then: log in to **your** Claude (Claude Code keyless, or `export ANTHROPIC_API_KEY=…`),
and — when you deploy — **your** Cloudflare/Vercel. Export a finished app as its
own repo with `area export <app> --repo <your-url> --push`.

## Phase 0 — setup

Prereqs installed so far: `uv`, project skeleton, pinned engine deps.

```bash
# 1. Create the Python 3.12 virtualenv (OpenHands requires >=3.12)
uv venv --python 3.12

# 2. Install engine deps (pinned — see requirements.lock)
uv pip install -r requirements.lock

# 3. Configure an LLM key
cp config/llm.example.env config/llm.env   # then edit config/llm.env

# 4. Smoke-test the engine (needs an LLM key; Docker only for sandboxed runtimes)
set -a && source config/llm.env && set +a
uv run python scripts/01_hello_world.py
```

## Reverse-engineering tiers (Flow B)

- **Tier 1 (default, low risk):** OpenHands' built-in browser + repomix + grep. No REA.
- **Tier 2 (opt-in, authorized targets only):** REA MCP server, declared in `.mcp.json`.
  **Pin `rea-agents` to an exact version before real use** — it ships breaking changes
  across minor versions. Only point it at software you are authorized to analyze.

## Docs

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — the system map (the oracle-loop spine, the pipeline, the 7 gates, the module layout). **Start here to understand the code.**
- [CONTRIBUTING.md](CONTRIBUTING.md) — setup, tests, and how to extend it (add a gate / backend).
- [CLAUDE.md](CLAUDE.md) — the rules the build agent follows (the oracle-loop discipline).
- [PLAN.md](PLAN.md) — architecture plan, decisions, and production-readiness status.

## Layout

```
area/        orchestrator (intake, re, spec, engine, verify, deploy, memory)
workspace/   generated apps land here (apps/<name> + specs/<name>)
config/      llm.env (gitignored) + examples
scripts/     runnable smoke tests / demos
tools/       deterministic shell gates (lock/verify-holdout, gate, provenance)
docs/        ARCHITECTURE.md, ADRs, RUNNER.md, requirements inbox
PLAN.md      architecture plan (audited)
```
