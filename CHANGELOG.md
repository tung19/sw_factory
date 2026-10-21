# Changelog

All notable changes to AREA. Format: [Keep a Changelog](https://keepachangelog.com/);
versioning: [SemVer](https://semver.org/). Pre-1.0 — the surface may still change.

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

### Gates (7)
- `holdout` (the locked oracle), `audit` (two-tier: tsc + npm-audit + secrets, +
  advisory risky-pattern scan), `e2e` (Playwright, forced before deploying an
  auth/session/form app), `chaos`, `nfr` (static budget), `perf` (live load),
  `product` (independent product-fit reviewer). `--all` runs them after a build and
  blocks the deploy on a failure.

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
