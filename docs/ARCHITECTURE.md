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
| **B+ — Adapt** | `area adapt <reference> "<requirement>"` | research-augmented clone & adapt: research comparable projects + the reference → a **requirement-anchored** spec (requirement wins), one-shot clarify, then build. See [`docs/features/area-adapt.md`](features/area-adapt.md) |
| Hybrid intake | `area intake <aidlc-artifacts>` | AI-DLC Inception artifacts → spec → build |
| Iterate | `area iterate <app> "<change>"` | fold a change into the existing spec → **re-lock** oracle → rebuild |

Flows A/B/intake/iterate converge on the **same pipeline** in
[`area/pipeline.py`](../area/pipeline.py); **adapt** ([`area/adapt.py`](../area/adapt.py))
adds a research → requirement-anchored-synthesis → clarify front-end that emits a
spec and hands off to that pipeline (`area/research.py` + `area/seed.py`).

## The pipeline, stage by stage

Requirement/source
→ **intake** → **spec** → *(design)* → **lock holdout** → **build-to-green** → **gates** → **provenance** → *(deploy)*

| Stage | Module | What happens |
|-------|--------|--------------|
| Intake | `area/intake/aidlc.py`, `area/re/extract.py` | normalize the input (AI-DLC artifacts, or reverse-engineer a reference app — RE Tier 1 built-in, Tier 2 = REA MCP) |
| Spec | `area/spec/` (`extract.py`, `models.py`, `review.py`) | produce `spec.yaml` + `acceptance.yaml` + `assumptions.yaml`; an **independent reviewer** flags material ambiguities; `--clarify` (default on) stops before building if the requirement is too vague |
| Design | `area/design.py` | architect stage (`design.md`); auto-runs for a non-trivial app (entities or ≥3 features) |
| Lock holdout | `area/verify/holdout.py` | **`--tdd` (the default)**: an **independent subagent** authors the acceptance tests under `__tests__/_holdout/` from the spec ONLY, in an EMPTY directory, *before any implementation exists*, then they are **checksum-locked** (see "Independence enforcement"). The non-TDD `verify` gate authors the same suite **after** the build and is a weaker oracle — see "Two oracle strengths" |
| Build to green | `area/build/`, `area/engine/adapter.py` | the build agent writes app code until the **locked** holdout passes; it may never edit the holdout. For a **clone** the oracle also carries a UI term (`_with_ui_parity`): once the tests are green, visual parity against the captured reference must clear `visual.UI_ORACLE_FLOOR`, or the shortfall goes back as feedback — otherwise the loop converged on behaviour and the look was never guaranteed |
| Gates | `area/verify/*` | the 9 gates below; a blocking failure stops the deploy |
| Provenance | `area/provenance.py` | SLSA-style record {spec digest → gates passed → artifact sha256} so a later deploy can prove the build wasn't modified after gating |
| Outer loop | `profiles/*.yaml`, `area/profile.py`, `area/evals.py` | every agent run is stamped with the **profile digest** that produced it, so `area evals` can grade a change to AREA's own prompts/skills/knobs against the previous version — the spine applied to the factory itself (see "The outer loop" below) |
| Deploy | `area/deploy/` | multi-provider (Cloudflare vinext / Vercel / plain), auto-detected; verifies provenance first |

Post-build, a **reality report** ([`area/reality.py`](../area/reality.py)) prints the
material assumptions chosen + how to preview + the `area iterate` command, so the
human closes the intent loop.

## The gates (`area/verify/`)

Run individually (`area <gate> <app>`) or together after a build (`--<gate>` flags, or `--all`).
Posture rule: **deterministic gates block; LLM-judgement gates are advisory until `--strict`.**

| Gate | Module | Kind | Blocks? |
|------|--------|------|---------|
| holdout / `verify` | `holdout.py` | the locked oracle (independent agent authors, runner executes). `--tdd` removes this gate as redundant — the pre-locked holdout already drove the build; so this gate only runs on the **non-TDD** path, where it is the weaker of the two oracles ("Two oracle strengths") | **yes** (the oracle) |
| `audit` | `audit.py` | tier-1 deterministic (tsc + `npm audit` + secrets); tier-2 risky-pattern scan | tier-1 yes; tier-2 **injection class (XSS/eval/SQL-injection) blocks by default** (`--no-block-injection` downgrades), the rest on `--strict` |
| `e2e` | `e2e.py` | Playwright drives the real UI (one spec per AC) | **forced before deploy** for auth/session/form apps (`--no-e2e` overrides) |
| `chaos` | `chaos.py` | adversarial inputs + resilience; hardens the app | yes (chaos suite) |
| `nfr` | `nfr.py` | deterministic static budget (bundle/deps/install size) | spec `nfr.yaml` blocks; defaults advisory unless `--strict` |
| `perf` | `perf.py` | boots the app, fires concurrent load, measures p50/p95/p99 + throughput + error-rate | spec `perf.yaml` blocks; defaults advisory unless `--strict` |
| `visual` | `visual.py` | 3-layer visual parity for a CLONE (design tokens · DOM structure · pixels) against the captured reference UI in `specs/<name>/_ui/`. Auto-selected when a reference UI was captured; the UI is also a term in the BUILD oracle (`UI_ORACLE_FLOOR = 0.45`, which asks "did you use the vendored reference at all", not "is it pixel-perfect") | spec `visual.yaml` blocks; otherwise advisory unless `--strict`. A committed floor that cannot be measured FAILS |
| `product` | `product.py` | independent reviewer judges product-fit / UX gaps (*did we build the right thing?*) | advisory unless `--strict`; under `--strict` it also fails when it could NOT form a verdict — no spec, no reviewer, or an unparseable reply — same rule as nfr/visual |
| `cost` | `cost.py` | hard cost cap: total build spend (across retries, app-scoped from `obs`) vs budget — the HARD complement to `--budget`'s soft per-run cap | spec `cost.yaml` (`max_usd:`) / `--cost-max` blocks; default advisory unless `--strict` |

The gate set is a single source — `cli._GATE_ORDER` drives the `_finish` selection,
the `_run_gate` dispatch, and the `--all` help, so it can't drift. Add a gate via
the registry (see CONTRIBUTING).

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

The holdout oracle is protected at three layers. **They do not all cover the same
agent** — AREA runs builders in two different contexts, so be precise about which:

- **(A) a Claude Code session rooted in this repo** — the native flows, where *you* are
  the agent following `CLAUDE.md` and the `build-from-docs` / `clone-from-source` skills.
- **(B) the autonomous build agent** — the Claude Code CLI child that `area run/clone
  --tdd` spawns, rooted at the generated app's directory.

1. **Checksum lock** — `tools/lock-holdout.sh` writes `workspace/specs/<name>/holdout.lock`
   (a sha256 of every holdout file except the escape hatch). A `--tdd` build also keeps
   the lock in memory and persists it (`area/verify/holdout.py`). `tools/verify-holdout-intact.sh`
   re-checks it before/after each build step.
   *Covers A and B — but it **detects and reverts**, it does not prevent the write.*
2. **PreToolUse hook** — [`tools/hooks/guard_holdout.py`](../tools/hooks/guard_holdout.py),
   wired from [`.claude/settings.json`](../.claude/settings.json), **blocks** any
   Edit/Write to a locked holdout at the editor level (turns CLAUDE.md's "don't" into
   "can't"). Travels with the clone, and is inert until the user trusts the project.
   *Covers **A only**.* `area/skills.py` copies skills into a generated app but installs
   no `.claude/settings.json` there, so the hook never reaches agent B — for B the
   enforcement is layer 1 (detect-and-revert) plus layer 3. See
   [secure-factory-gap-assessment.md](secure-factory-gap-assessment.md) item 3.
3. **The `_CHALLENGE.md` escape hatch** — if a builder believes a locked test is *wrong*
   it writes `__tests__/_holdout/_CHALLENGE.md`; an **independent verifier** (never the
   builder) re-adjudicates against the spec and re-locks. This is "evolving tests under
   governance", not tampering. *Covers A and B.*

### Two oracle strengths — `--tdd` vs the non-TDD `verify` gate

`CLAUDE.md` enforcement **(a)** is: *author the holdout from the spec ONLY, before any
implementation exists.* Only one of AREA's two paths can satisfy that, and the
difference is worth stating plainly rather than calling both "the locked oracle":

| | `--tdd` (default) | non-TDD `verify` gate |
|---|---|---|
| When the oracle is authored | **before** the build | **after** the build |
| What the author can see | the spec only, in an EMPTY dir | the spec **and the implementation** |
| Who defines the contract | the tests (`CONTRACT.md`) — the code must satisfy them | the code — the tests must import "its real modules as the app exposes them" |
| Satisfies enforcement (a) | **yes** | **no, by construction** |

Both paths keep independence of *reasoning* (a separate agent, fresh context, forbidden
from touching app source). The non-TDD path loses independence of *information*: an
author that reads the implementation can encode what the code does rather than what the
AC requires. The gate therefore prints a warning when it authors against existing
source, and `--tdd` is the path to prefer.

**A locked oracle is never re-authored.** `author_until` refuses when
`specs/<name>/holdout.lock` exists and matches (it reuses the suite) and raises when it
does not match (tamper → revert, or `_CHALLENGE.md`). Without that guard, running
`area verify` on a `--tdd`-built app replaced the strong pre-locked oracle with a
post-build one *and* rewrote the lock to match — after which
`tools/verify-holdout-intact.sh` reported the oracle intact. The one sanctioned way to
replace a locked oracle is `readjudicate`, which clears the lock first.

## The outer loop (grading the factory, not the app)

The gates decide whether an **app** may ship. Nothing decided whether a change to the
**factory** was an improvement — edit a prompt and no measurement told you, which is the
one thing AREA's spine forbids, applied to AREA itself.

- **`profiles/<kind>.yaml`** — one versioned artifact per kind of agent (16: builder,
  holdout-author, holdout-fixer, spec-extractor, …). It declares the obs label globs
  that attribute a run to it, the prompt symbols whose **source is hashed** into its
  digest, whether the skills pack is installed, and per-kind `agent_iters` /
  `budget_usd` / `max_iters` defaults (a CLI flag still wins). Prompts stay in Python:
  they are interpolated f-strings with branching, and hashing their source gives the
  same attribution as rewriting them as templates would.
- **The digest** changes when a prompt, a skill, or a knob changes — that is what makes
  a "version" of a kind.
- **`obs.log_run`** stamps `(profile, profile_digest)` on every run from one place, so
  every agent call site is attributed without being touched.
- **`area evals` / `make evals`** compares a kind's current version against the previous
  one (first-try rate, pass rate, avg attempts, avg cost) and fails `--check` on a
  regression. It is **not** a member of `_GATE_ORDER` — an app must not be blocked
  because a prompt regressed, and this must not run after every build.

`holdout-author` and `holdout-fixer` are deliberately separate profiles in the same
module: one writes the oracle, the other fixes code against it, and keeping them apart
is the independence guarantee.

## Execution engine

The build/verify agents run through one seam: [`area/engine/adapter.py`](../area/engine/adapter.py).
It wraps the **OpenHands `software-agent-sdk`**, which is **vendored in-tree** at
`vendor/software-agent-sdk/` (git subtree, MIT) so the whole thing is one source and
doesn't break on an upstream PyPI release. `run_until(agent, …, oracle)` is the
convergence loop: send task → run → check oracle → re-prompt on failure, up to a cap;
the attempt it goes green on is logged as `outer_iters` (the determinism signal).

Backend is keyless ACP (Claude Code) by default; `--backend llm` / `--model` select
alternatives. The engine enforces the cost/step caps (`--budget`, `--agent-iters`).

**Secret scoping:** while the agent runs (`_run_retry` → `conv.run()`), the engine
**scrubs deploy/cloud secrets** (Cloudflare/Vercel/Postgres/KV/GitHub tokens, …) from
its environment (`_scrubbed_agent_env`) and restores them after — so untrusted
content the agent reads (cloned source, web research, a reverse-engineered app)
can't exfiltrate them via the terminal. Deploy runs in a separate, non-agent phase,
so it still sees the tokens.

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
  cli.py             the `area` command surface (see "Commands"); _GATE_ORDER registry
  engine/adapter.py  the ONE seam to the agent engine (OpenHands SDK, vendored); secret scrub
  spec/              requirement → spec.yaml + acceptance.yaml (+ independent review)
  intake/aidlc.py    AI-DLC artifacts → spec
  re/extract.py      reverse-engineer a reference app (Flow B); REA Tier-2 config
  research.py        Flow B+ P1: survey comparable projects → research brief
  adapt.py           Flow B+ P2/P3 + capstone: requirement-anchored synthesis + data plan + the `area adapt` pipeline
  seed.py            Flow B+ P4: opt-in attested seed-from-reference (robots/PII/cap)
  verify/            the 9 gates (holdout, audit, e2e, chaos, nfr, perf, visual, product, cost)
  build/             the build prompts + cf_scaffold.py (deterministic vinext fixes)
  design.py          architect stage → design.md
  profile.py         one versioned artifact per agent kind (profiles/*.yaml) + digest
  evals.py           grade a FACTORY change against the previous profile version
  screen.py          redact credentials in anything untrusted the agent will read
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

`run` · `clone` · `adapt` · `intake` · `iterate` — build flows ·
`research` — Flow B+ research stage (standalone) ·
`verify` · `audit` · `e2e` · `chaos` · `perf` · `cost` (+ `--nfr`/`--product` as gate flags) — gates ·
`cf-fix` · `cf-clone` — deterministic vinext build fixes ·
`deploy` · `rollback` · `provenance` · `export` — ship ·
`gui` · `doctor` · `obs` · `mem` · `design` · `heal` · `monitor` · `status` · `watch` — operate.

## Workspace layout (per product)

Each product is isolated by name:
- `workspace/apps/<name>/` — the app source (+ `__tests__/_holdout/` the locked oracle, `.area/provenance.json`)
- `workspace/specs/<name>/` — `spec.yaml`, `acceptance.yaml`, `assumptions.yaml`, `design.md`, `holdout.lock`, optional `nfr.yaml`/`perf.yaml`/`cost.yaml` budgets, and (adapt) `research/brief.json` + `adapt-notes.md`

A name is required (prompted if omitted) so builds never collide. `area export <name>`
hands a finished app off as its own git repo.

## Not on this branch

The multi-user **coordinator + runner** SaaS (web dashboard, relay, ACP backend) lives
on `saas-coordinator-runner`. This `main` is the internal, Claude-Code-native path:
*you* are the agent and the LLM — no ACP wrapper, no runner.
