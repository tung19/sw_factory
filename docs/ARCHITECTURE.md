# AREA — Architecture

A map of the codebase for someone seeing it for the first time. For the *why*
(decisions, rejected alternatives, status) see [PLAN.md](../PLAN.md); for the
rules the build agent follows see [CLAUDE.md](../CLAUDE.md); for how to set up and
extend it see [CONTRIBUTING.md](../CONTRIBUTING.md).

AREA is an **autonomous software factory**: give it a requirement (or a reference
app) and it produces a working, gated, optionally-deployed app — without a human
grading each step. It runs **local-first**: on your machine, with your Claude and
your Cloudflare/Vercel; nothing leaves the box.

## The spine (read this first)

> **Quality ≤ strength + INDEPENDENCE of the oracle.**

Everything else serves one idea: **never let the same reasoning both write AND
grade the code.** Before any implementation exists, AREA locks an **independent
acceptance-test suite** (the *holdout oracle*), then builds until that frozen
suite passes ("oracle green"), then stops. The human (Tung) is the top gate for
the only question the loop can't answer itself — *"is the oracle itself correct?"*

If you change one thing in this repo, do not break that independence.

## Two entry flows, one pipeline

| Flow | Entry | What it is |
|------|-------|-----------|
| **A — Requirement** | `area run "<requirement>"` | NL requirement → spec → build |
| **B — Clone** | `area clone <url\|repo\|path>` | reverse-engineer a reference app → spec → behavioral-parity build (the reference *is* the oracle) |
| Hybrid intake | `area intake <aidlc-artifacts>` | AI-DLC Inception artifacts → spec → build |
| Iterate | `area iterate <app> "<change>"` | fold a change into the existing spec → **re-lock** oracle → rebuild |

All four converge on the **same pipeline** in [`area/pipeline.py`](../area/pipeline.py).

## The pipeline, stage by stage

Requirement/source
→ **intake** → **spec** → *(design)* → **lock holdout** → **build-to-green** → **gates** → **provenance** → *(deploy)*

| Stage | Module | What happens |
|-------|--------|--------------|
| Intake | `area/intake/aidlc.py`, `area/re/extract.py` | normalize the input (AI-DLC artifacts, or reverse-engineer a reference app — RE Tier 1 built-in, Tier 2 = REA MCP) |
| Spec | `area/spec/` (`extract.py`, `models.py`, `review.py`) | produce `spec.yaml` + `acceptance.yaml` + `assumptions.yaml`; an **independent reviewer** flags material ambiguities; `--clarify` (default on) stops before building if the requirement is too vague |
| Design | `area/design.py` | architect stage (`design.md`); auto-runs for a non-trivial app (entities or ≥3 features) |
| Lock holdout | `area/verify/holdout.py` | an **independent subagent** authors the acceptance tests under `__tests__/_holdout/` from the spec ONLY, then they are **checksum-locked** (see "Independence enforcement") |
| Build to green | `area/build/`, `area/engine/adapter.py` | the build agent writes app code until the **locked** holdout passes; it may never edit the holdout |
| Gates | `area/verify/*` | the 7 gates below; a blocking failure stops the deploy |
| Provenance | `area/provenance.py` | SLSA-style record {spec digest → gates passed → artifact sha256} so a later deploy can prove the build wasn't modified after gating |
| Deploy | `area/deploy/` | multi-provider (Cloudflare vinext / Vercel / plain), auto-detected; verifies provenance first |

Post-build, a **reality report** ([`area/reality.py`](../area/reality.py)) prints the
material assumptions chosen + how to preview + the `area iterate` command, so the
human closes the intent loop.

## The gates (`area/verify/`)

Run individually (`area <gate> <app>`) or together after a build (`--<gate>` flags, or `--all`).
Posture rule: **deterministic gates block; LLM-judgement gates are advisory until `--strict`.**

| Gate | Module | Kind | Blocks? |
|------|--------|------|---------|
| holdout / `verify` | `holdout.py` | the locked oracle (independent agent authors, runner executes) | **yes** (the oracle) |
| `audit` | `audit.py` | tier-1 deterministic (tsc + `npm audit` + secrets); tier-2 advisory risky-pattern scan | tier-1 yes; tier-2 on `--strict` |
| `e2e` | `e2e.py` | Playwright drives the real UI (one spec per AC) | **forced before deploy** for auth/session/form apps (`--no-e2e` overrides) |
| `chaos` | `chaos.py` | adversarial inputs + resilience; hardens the app | yes (chaos suite) |
| `nfr` | `nfr.py` | deterministic static budget (bundle/deps/install size) | spec `nfr.yaml` blocks; defaults advisory unless `--strict` |
| `perf` | `perf.py` | boots the app, fires concurrent load, measures p50/p95/p99 + throughput + error-rate | spec `perf.yaml` blocks; defaults advisory unless `--strict` |
| `product` | `product.py` | independent reviewer judges product-fit / UX gaps | advisory unless `--strict` |

Why both `nfr` and `perf`: `nfr` measures the *artifact* statically (CI-friendly, no
run); `perf` measures the *running app* (catches runtime regressions a static
measure can't). Both boot/measure on a **free ephemeral port** so a busy `:3000`
(e.g. a local Langfuse) can't derail them.

**Independence caveat (important):** only the **holdout** is a truly *independent*
oracle — authored by a separate agent from the spec alone, checksum-locked, and
guard-hooked. `product` and the spec reviewer are also independent (separate
keyless reviewers via `area.engine.ask_cli`). But `e2e`, `chaos`, and `audit --fix`
drive the **implementer-style build agent** — it authors those tests *and* makes
them pass, and they are not locked — so a green `e2e`/`chaos` is same-agent
*hardening*, not an independent check. Don't over-trust them the way you trust the
holdout. (All gates now also confirm their runner actually executed tests, not just
exited 0 — see `area/verify/_runners.py`.)

## Independence enforcement (the heart)

The holdout oracle is protected at three layers:

1. **Checksum lock** — `tools/lock-holdout.sh` writes `workspace/specs/<name>/holdout.lock`
   (a sha256 of every holdout file except the escape hatch). A `--tdd` build also keeps
   the lock in memory and persists it (`area/verify/holdout.py`). `tools/verify-holdout-intact.sh`
   re-checks it before/after each build step.
2. **PreToolUse hook** — [`tools/hooks/guard_holdout.py`](../tools/hooks/guard_holdout.py),
   wired from [`.claude/settings.json`](../.claude/settings.json), **blocks** any
   Edit/Write to a locked holdout at the editor level (turns CLAUDE.md's "don't" into
   "can't"). Travels with the clone.
3. **The `_CHALLENGE.md` escape hatch** — the build agent cannot edit a locked test, but
   if it believes one is *wrong* it writes `__tests__/_holdout/_CHALLENGE.md`; an
   **independent verifier** (never the builder) re-adjudicates against the spec and
   re-locks. This is "evolving tests under governance", not tampering.

## Execution engine

The build/verify agents run through one seam: [`area/engine/adapter.py`](../area/engine/adapter.py).
It wraps the **OpenHands `software-agent-sdk`**, which is **vendored in-tree** at
`vendor/software-agent-sdk/` (git subtree, MIT) so the whole thing is one source and
doesn't break on an upstream PyPI release. `run_until(agent, …, oracle)` is the
convergence loop: send task → run → check oracle → re-prompt on failure, up to a cap;
the attempt it goes green on is logged as `outer_iters` (the determinism signal).

Backend is keyless ACP (Claude Code) by default; `--backend llm` / `--model` select
alternatives. The engine enforces the cost/step caps (`--budget`, `--agent-iters`).

## Observability

- [`area/obs.py`](../area/obs.py) — one JSONL line per agent run (`workspace/.area/runs.jsonl`):
  cost, duration, outcome, `outer_iters`. `summary()` aggregates cost/stage +
  **determinism** (first-try rate, retry rate, avg attempts). Surfaced by `area obs`,
  the dashboard `/api/metrics` card, and the experience store.
- [`area/trace.py`](../area/trace.py) — optional Langfuse process-viz (1 trace/pipeline,
  1 span/agent-run). No-op without the SDK/keys.
- [`area/memory/`](../area/memory/) — pitfalls learned (a failure overcome → a lesson re-injected later).

## Module map

```
area/
  pipeline.py        the shared pipeline (run / clone / intake / iterate)
  cli.py             the `area` command surface (see "Commands")
  engine/adapter.py  the ONE seam to the agent engine (OpenHands SDK, vendored)
  spec/              requirement → spec.yaml + acceptance.yaml (+ independent review)
  intake/aidlc.py    AI-DLC artifacts → spec
  re/extract.py      reverse-engineer a reference app (Flow B); REA Tier-2 config
  verify/            the 7 gates (holdout, audit, e2e, chaos, nfr, perf, product)
  design.py          architect stage → design.md
  provenance.py      SLSA-style build attestation + verify-before-deploy
  reality.py         post-build "did we build what you meant?" report
  deploy/            cloudflare.py · vercel.py (auto-detected, provenance-gated)
  heal.py            fix a built app at the SPEC level from an error, regen
  monitor.py         probe deployed app health/latency; self-heal watch loop
  obs.py trace.py memory/     observability + experience store
  web/               the dashboard (Starlette): server, jobs, chat, upload, auth
  skills.py          installs .claude/skills/* into each built app's project scope
  doctor.py export.py preview.py _util.py   setup check · hand-off as own repo · open · safe_name
tools/               deterministic shell gates (lock/verify-holdout, gate, provenance, scaffold, deploy)
  hooks/guard_holdout.py   the PreToolUse holdout guard
.claude/skills/      AREA's own hard-won knowledge as Claude Code skills
vendor/software-agent-sdk/   the engine (OpenHands SDK), vendored
workspace/           generated apps (apps/<name>) + specs (specs/<name>) — gitignored
docs/ · PLAN.md · CLAUDE.md · README.md · CONTRIBUTING.md
```

## Commands (`area --help`)

`run` · `clone` · `intake` · `iterate` — build flows ·
`verify` · `audit` · `e2e` · `chaos` · `perf` (+ `--nfr`/`--product` as gate flags) — gates ·
`deploy` · `rollback` · `provenance` · `export` — ship ·
`gui` · `doctor` · `obs` · `mem` · `design` · `heal` · `monitor` · `status` · `watch` — operate.

## Workspace layout (per product)

Each product is isolated by name:
- `workspace/apps/<name>/` — the app source (+ `__tests__/_holdout/` the locked oracle, `.area/provenance.json`)
- `workspace/specs/<name>/` — `spec.yaml`, `acceptance.yaml`, `assumptions.yaml`, `design.md`, `holdout.lock`, optional `nfr.yaml`/`perf.yaml` budgets

A name is required (prompted if omitted) so builds never collide. `area export <name>`
hands a finished app off as its own git repo.

## Not on this branch

The multi-user **coordinator + runner** SaaS (web dashboard, relay, ACP backend) lives
on `saas-coordinator-runner`. This `main` is the internal, Claude-Code-native path:
*you* are the agent and the LLM — no ACP wrapper, no runner.
