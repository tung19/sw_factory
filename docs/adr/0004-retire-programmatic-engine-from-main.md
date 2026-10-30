# ADR 0004 — Retire the programmatic OpenHands engine from `main`

Status: **Proposed** (awaiting Tung's approval; direction decided 2026-10-30, staging not yet executed)

## Context

`CLAUDE.md:103-105` states the thesis of this branch:

> This `main` is the **internal, Claude-Code-native** path: fast, no ACP wrapper, no
> runner — *you* are the agent and the LLM. The coordinator + runner (web dashboard,
> relay, ACP backend) lives on `saas-coordinator-runner`.

The deep evaluation against `obra/superpowers` (see
[deep-eval-superpowers.md](../deep-eval-superpowers.md), finding **L1**) showed the code
contradicts that thesis:

- `area/engine/adapter.py` is a wrapper over the **30M** vendored OpenHands SDK
  (`vendor/software-agent-sdk`). **Both** backends run through it:
  - `--backend acp` → `ACPAgent`, drives the Claude Code CLI *over ACP* (an ACP wrapper);
  - `--backend llm` → an OpenHands-native agent over LiteLLM (needs a key).
- Every `area` subcommand **defaults to `--backend acp`**.
- The genuinely "native" path — the skills (`build-from-docs`, `clone-from-source`) plus
  `tools/*.sh`, driven by Claude Code directly — **bypasses `area/engine` entirely**.

So there are two independent ways to drive the factory: the skill-native path (the thesis)
and the programmatic OpenHands engine (`area run/clone/iterate/...`). The second duplicates
the first's job, carries a 30M vendored dependency, is an ACP wrapper by any honest reading,
and conceptually belongs with the runner on `saas-coordinator-runner` — which is exactly
where `CLAUDE.md` already says the ACP backend and runner live.

**Decision taken with Tung (2026-10-30):** the native path is the intended one for `main`.
Retire the programmatic engine from `main`. This ADR is the staged plan; it is **not**
executed until approved.

## What the blast radius actually is (verified)

`grep` of what each module imports from `area.engine` splits cleanly into two groups:

**Group H — helper-only (no agent, trivially severable from OpenHands):**
| Module | Imports |
|---|---|
| `area/build/cf_scaffold.py`, `area/verify/nfr.py`, `area/verify/perf.py` | `scrubbed_env` |
| `area/pipeline.py`, `area/adapt.py`, `area/monitor.py` | `Backend` (a type literal) |

**Group A — genuinely drives an agent (the OpenHands-dependent core):**
`area/design.py`, `area/heal.py`, `area/research.py`, `area/spec/extract.py`,
`area/spec/review.py` (`ask_cli`), `area/re/extract.py`, `area/intake/aidlc.py`,
`area/inception/engine.py`, `area/build/nextjs.py`, and the **author/fix phases** of the
gates `area/verify/{audit,chaos,e2e,holdout,product}.py`
(`build_agent` / `run_until` / `run_once` / `run_goal` / `ask_cli` / `command_verifier`).

The deterministic *checking* (run `npm test`, measure, diff) does not need an agent; the
coupling is that the gates currently also *author* or *fix* via the engine.

## Decision — staged retirement

### Stage 0 — sever Group H (safe, mechanical, no behavior change)
Extract `scrubbed_env`, the `Backend` type, and `command_verifier` into a stdlib-only leaf
module (e.g. `area/engine_util.py`, importing no OpenHands), and repoint Group H to it. After
this, 6 modules + the whole deterministic gate path no longer pull in the 30M SDK transitively.
Prove with an import-graph test: `import area.verify.nfr` must not import `openhands`.

### Stage 1 — inventory Group A and decide per command
For each agent-driving entrypoint, choose one of:
- **Move to `saas-coordinator-runner`** — it is a headless/automated driver (the honest home
  for `area run/clone/iterate` as programmatic agents), or
- **Repoint to a native executor** — a thin driver that calls Claude Code directly (no
  OpenHands `ACPAgent`), preserving the `run_until(verifier)` self-correct loop against the
  deterministic verifiers, for the commands worth keeping headless on `main`.

Do not delete anything in this stage; produce the mapping table and a test matrix first.

### Stage 2 — execute the chosen moves on a branch
Per the chosen mapping: relocate or repoint, delete `area/engine/adapter.py` and
`vendor/software-agent-sdk` **only** once nothing on `main` imports them, and update
`.claude` + packaging. Gate: full suite green, `mypy` strict clean, no `openhands` import
remains under `area/` on `main`.

### Stage 3 — reconcile the record
Update `CLAUDE.md` so the thesis and the code agree, and resolve finding **L4** (`area/web`
dashboard) the same way — move to the saas branch or state plainly it is a local-only dev
tool on `main`. Correct any doc that described the engine as the default driver.

## Consequences

- **`main` matches its thesis:** driven by skills + `tools/*.sh` + the deterministic
  gates/provenance/deploy that need no agent; ~30M and an ACP wrapper leave the branch.
- **No capability is lost** — the programmatic driver still exists on
  `saas-coordinator-runner`, which is where the multi-user story needs it anyway (and where
  it must gain the sandbox/egress/identity boundaries `secure-factory-gap-assessment.md`
  calls for).
- **Risk:** Group A is ~16 modules; a botched move breaks `area run/clone/iterate`. Mitigated
  by staging (H first, behavior-preserving), the import-graph test, and never deleting before
  the importers are gone.
- **`area evals` churn:** touching prompt sources re-versions several kinds (the M9 cost
  problem). The cheap `writing-skills` wording gate (deep-eval A3, Tier-1) should land first so
  these moves can be validated without the full matched-pair outcome eval.

## Status / next

Awaiting approval of this staging. On approval, execute **Stage 0 only** first (safe, reversible,
self-proving) and report before proceeding to Stage 1.
