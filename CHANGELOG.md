# Changelog

All notable changes to AREA. Format: [Keep a Changelog](https://keepachangelog.com/);
versioning: [SemVer](https://semver.org/). Pre-1.0 — the surface may still change.

## Unreleased

### Fixed
- **`area evals` graded the factory on a constant.** `run_once` recorded `passed=True`
  although it takes no Verifier, so the ledger said 109 of 110 runs passed. The field is
  gone; `obs.log_run` already defaulted it to `None` and `evals.metrics` already excluded
  unjudged runs.
- **`area evals` compared versions that ran different work.** A version is now graded only
  on the tasks both versions ran (keyed on the app name `obs.set_app()` stamps); with no
  shared task the verdict is `unpaired` and nothing is certified. Adopted from Harness²'s
  "probe" step (arXiv:2610.14224) — and only that: its premise, refinement without
  ground-truth verifiers, is the opposite of AREA's spine.

- **The build agent was shipped a stale skills pack.** `vinext-cf-build` was rewritten in
  `.claude/skills/` when `area cf-fix`/`cf-clone` shipped, but `area.skills` installs from
  `skills/`, which still held the older text with zero mentions of either — so the
  automation never reached the builder and the attestation digested the stale copy. The
  maintained text now ships, and a test enforces that any skill in both trees is identical.

- **The build ran with the deploy tokens in its environment.** The scrub covered only
  the agent exchange, so `verify()` — which runs `npm install` on an agent-authored
  `package.json`, then its build and tests — inherited them. `command_verifier` now hands
  the child a filtered `env=`, `run_until` scrubs around an arbitrary verifier, and the
  holdout oracle, the three per-module `_env()` helpers and `ask_cli` are swept too.
- **`perf` failed open on a committed budget.** `return True` ran before `blocking` was
  consulted, so a server that never started passed a committed `perf.yaml`. Fixed in the
  same change, because scrubbing perf's environment makes that failure more likely.

### Added
- `evals/tasks.yaml` — the declared fixed A/B set for a factory change, plus
  `area evals --tasks` to print it and `--any-task` to compare on any shared task.

## [Unreleased]

The factory's capabilities to date (grouped; see the git history for detail).

### Core — the oracle-loop
- Two entry flows on one pipeline: **Flow A** (requirement → spec → build) and
  **Flow B** (clone a reference app → reverse-engineer → build), plus `intake`
  (AI-DLC artifacts) and `iterate` (change an existing app).
- **`--tdd`**: an independent agent authors the acceptance tests from the spec,
  they are **checksum-locked**, and the build runs until that frozen suite passes.
  A PreToolUse hook blocks edits to a locked holdout; the gate confirms the suite
  actually executed (not just exit 0).
- **Clarify-by-default** + an independent spec-vs-intent reviewer (stop on material
  ambiguity instead of guessing).

### Gates (9)
- `holdout` (the locked oracle), `audit` (two-tier: tsc + npm-audit + secrets, +
  a risky-pattern scan whose **injection class — XSS/eval/SQL-injection — blocks by
  default**), `e2e` (Playwright, forced before deploying an auth/session/form app),
  `chaos`, `nfr` (static budget, enforces a committed budget it can't measure),
  `perf` (live load), `visual` (3-layer visual-parity for a clone; advisory until a committed `visual.yaml`), `product` (independent product-fit reviewer), and **`cost`**
  (hard total-spend cap, app-scoped from obs — the HARD complement to `--budget`).
  The gate set is a single source (`_GATE_ORDER`) driving selection, dispatch, and
  `--all`. `--all` runs them after a build and blocks the deploy on a failure.

### Attestation & the deploy gate (secure-factory assessment)
Measured against *The Secure Software Factory* (Agent Baseline v1) —
see [docs/secure-factory-gap-assessment.md](docs/secure-factory-gap-assessment.md).
- **Provenance tells the truth** (`area.slsa-like/v2`). `builder` names the real
  backend (it was a hardcoded literal, wrong for every `--backend llm` run). Per-gate
  records are `{ran, blocking, blocked}` plus `gatesNotRun`, so an **advisory** gate
  below its threshold is no longer attested identically to an enforced pass; posture
  comes from each gate's own budget loader, and is recorded as `null` rather than
  guessed when it can't be determined. A new `policy` block records model, backend,
  strictness, caps, the **factory's own git revision** and a digest of the skills
  pack — without which a past build could not be reconstructed.
- **The deploy gate fails closed.** A provenance check that *cannot run* now refuses
  instead of warning and deploying. An artifact AREA never gated does not ship unless
  asked (`--no-require-provenance` / `AREA_REQUIRE_PROVENANCE=0`); that env var was
  previously dead code, because `--require-provenance` is a `store_true` whose `False`
  was passed through explicitly.
- **High-impact actions are named and approved.** `tools/deploy.sh` no longer forces
  `--yes` (it silently bypassed the only human gate), the dashboard must carry an
  explicit `confirm: true`, and the prompt now names the real provider and says when a
  PRODUCTION database will be created/migrated. A failed datastore provision blocks the
  deploy (`--allow-provision-failure` to override) instead of shipping an app whose DB
  isn't there.
- `docs/ARCHITECTURE.md` states **which agent** each independence layer covers: the
  PreToolUse hook guards a Claude Code session rooted in the repo, not the autonomous
  ACP build agent, for which layer 1 is detect-and-revert.

### Boundaries: input screening, factory integrity, timeouts, a kill switch
Group 3 of the same assessment — the controls that make spending money on real builds
safe, and the last ones that need no deploy token.
- **Credentials are screened on the way IN** (`area/screen.py`, stdlib leaf). Every
  copy that reaches the agent is redacted — an untrusted reference (`_sample/` →
  `_ui/` → `.area-ui/`), uploads, AI-DLC artifacts — while `_sample/` stays byte-exact
  and is scanned-and-reported, because it is the evidence the clone was built from.
  Redactions are counted in `UiEvidence`/the manifest and **printed**, so a false
  positive is visible instead of quietly corrupting a clone. It carries its own
  Python-native patterns on purpose: the audit gate's regex is written for grep, and
  its `[[:space:]]` is a POSIX class that Python's `re` accepts and misreads.
- **The factory is pinned during a run** (`tools/verify-factory-intact.sh`). Checksums
  `area/`/`tools/`/`skills/`/`.claude/settings.json` before a build and fails it if they
  changed — a gate that graded with modified code proves nothing. The lock lives in the
  OS temp dir, not the workspace the agent can write, and the result is attested as
  `policy.factoryIntact`. `area doctor` warns when the workspace sits inside the repo.
- **Nothing runs unbounded any more.** `command_verifier` (the `npm install && build &&
  test` call), the holdout runner and every wrangler/vercel/psql invocation are capped;
  a timeout reports as an ordinary failure so the loop feeds it back instead of
  crashing. `run_until` gained a whole-loop wall clock (`AREA_MAX_WALL_S`, 1h default).
- **There is a kill switch.** `area._util.kill_process_group` (promoted from
  `perf._stop`, now the only implementation) kills the process GROUP; dashboard jobs
  start their own session, and `DELETE /api/jobs/{id}` plus a stop button can cancel
  one. The cost gate only measures after the fact, so a thrashing build needed this.
- The agent env scrub wraps the whole exchange, not only `run()`, with a drift guard
  so a new `send_message` call site cannot fall outside it again.
- `SECURITY.md` now states the gaps that remain (no sandbox, no egress boundary, no
  per-agent identity, unsigned attestation) instead of being silent about them, and
  `docs/RUNNER.md` + `Dockerfile.runner` carry a banner saying the `area runner` they
  describe does not exist on `main`.

### The outer loop: agent profiles + evals on the factory itself
Group 4 of the assessment, and the one that turns AREA's own spine on AREA.
- **`profiles/<kind>.yaml` + `area/profile.py`** — one versioned artifact per kind of
  agent (16 of them; the obs log's label families are the ground truth). A profile holds
  only what it controls or identifies: the label globs that attribute a run to it, the
  prompt symbols whose **source is hashed into a digest**, whether the skills pack is
  installed, and `agent_iters`/`budget_usd`/`max_iters` defaults used when a caller
  passes nothing (a CLI flag still wins). Editing a prompt, a skill or a knob produces a
  new digest. Prompts stay in Python — they are interpolated f-strings with real
  branching, so hashing their source buys the same attribution as a lossy template
  rewrite. Every default ships as `null`, so adoption changed no behaviour.
  `holdout-author` and `holdout-fixer` are deliberately separate profiles in the same
  module: that separation is the spine.
- **`obs.log_run` stamps `(profile, profile_digest)` on every run**, from one place — so
  all 19 agent call sites became attributable without being touched. Before this, 110
  recorded runs could not be tied to any prompt/skill/knob version.
- **`area evals [--check] [--strict]`, `make evals`** — grades each kind's *current*
  version against the previous one on first-try rate, pass rate, avg attempts and avg
  cost (cost compared relatively, so a cheap stage doubling is caught). A regression
  fails `--check`; so does an unloadable profile, because that silently stops attributing
  runs. "Not enough data" passes unless `--strict`. It is **not** in `_GATE_ORDER`, and a
  test pins that: the gate set decides whether an *app* ships, evals decides whether a
  change to the *factory* may be promoted.
- Honest limits, both reported rather than hidden: runs predating profiles carry no
  digest and are excluded from baselines, and the first report revealed that **5 of 16
  agent kinds have never run** in 110 recorded runs.
- `provenance` now records `policy.profiles` — the digest of every profile at build time.

### Flow B+ — `area adapt` (research-augmented clone & adapt)
- `area adapt <reference> "<requirement>"`: **research** comparable projects
  (`area/research.py` — discover → rank → top-5 → analyse the data dimension →
  brief) → **requirement-anchored synthesis** (`area/adapt.py` — the requirement
  wins on conflict, every item tagged with its source) → a **one-shot clarify** on
  the auto-filled gaps → a data plan (persistence + ingest/ETL) → spec written +
  `area intake` build handoff → **opt-in `--seed`** from the reference (`area/seed.py`
  — attestation + robots.txt / public-only / no-PII / cap). Spec:
  `docs/features/area-adapt.md`. (Logic shipped + tested; live LLM/web dogfood deferred.)

### Hardening (this cycle)
- **mypy `--strict`** across the whole `area` package (journey: coverage → the
  no-untyped-def family → full strict); a new untyped/`Any`/bare-generic def fails CI.
- **Deterministic vinext fixes**: `area cf-fix` (pin compat date to the installed
  workerd + braces/fflate audit overrides + vendored patched braces) and
  `area cf-clone` (reuse a known-good sibling toolchain). `uv.lock` re-locked to match
  `pyproject`.
- **Security/correctness audit remediation** (independent 4-dimension review, ~7/10,
  remediated over several rounds): tier-1 secrets scan catches `KEY = "…"`; D1
  migration filename `shlex`-quoted; Vercel migrations run in one transaction; the
  cost gate is app-scoped (obs rows tagged); the evidence trail filters by trace;
  the agent env is scrubbed of deploy/cloud secrets while it reads untrusted content;
  provenance covers more materials + no dir-name blind spot.

### Ship
- Multi-provider deploy (`--target cloudflare|vercel|plain`), auto-detected, with
  D1/Postgres provisioning. **SLSA-style provenance** attests the build and
  **blocks a deploy on a mismatch**. `area export` hands an app off as its own repo.

### AI-DLC front-end (governed Inception)
- `area inception` — human-approved bolts (intent → user stories → Units of Work →
  Testing Posture) producing contract-compliant artifacts; a dashboard tab; and an
  **end-to-end audit trail** (`area trace`) correlating Inception → build → gates →
  provenance under one id.

### Observability & ops
- `area obs` / `/api/metrics` — cost + **determinism** metrics (first-try rate,
  retry rate, avg attempts) from the run log. Langfuse process-viz (optional).
  `area monitor`/`status`/`watch` — probe + self-heal loop.

### Local-first & distribution
- Runs on your machine with your accounts; `scripts/install.sh` + `area doctor` +
  `make setup`. **`AREA_WORKSPACE`** moves generated apps out of the repo.

### Security
- Independently audited and hardened (oracle-must-run, audit-gate blind spots,
  clone-source RCE guard, provenance-blocks-by-default, token-in-URL leakage,
  engine-seam unification, …). See `SECURITY.md`.

### Developer experience
- `examples/taskboard` — a committed real app (source + spec + locked oracle +
  evidence). `area demo <name>` — run an example locally, **keyless**. Product-first
  README, `docs/ARCHITECTURE.md`, `CONTRIBUTING.md`, ADRs, `docs/CASE-STUDY.md`,
  `docs/UPGRADE-PLAN.md`. `ruff` in CI.
