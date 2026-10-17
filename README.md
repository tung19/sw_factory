# AREA

Internal AI software factory. Two entry flows, one shared pipeline:

- **Flow A — Requirement:** natural-language requirement → spec → develop → self-correcting loop → deploy.
- **Flow B — Clone:** a sample app → reverse-engineer (2 tiers) → spec → same pipeline.

**Execution core:** [OpenHands `software-agent-sdk`](https://github.com/OpenHands/software-agent-sdk) (pinned, wrapped by `area/engine`).
Full design + rationale (and why not MetaGPT / Specora / REA-as-core): see [PLAN.md](PLAN.md).

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

## Layout

```
area/        orchestrator (intake, re, spec, engine, verify, deploy, memory)
workspace/   generated apps land here
config/      llm.env (gitignored) + examples
scripts/     runnable smoke tests / demos
PLAN.md      architecture plan (audited)
```
