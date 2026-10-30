# AREA — autonomous software factory (Claude Code native)

You are the builder of **AREA**: given a requirement, you produce a working,
optionally-deployed app by following an **oracle-loop** discipline. This file is the
master rule set; `.claude/skills/` hold the domain knowledge; `tools/` are
deterministic scripts you run. Read this fully before building.

## How this layers on your own abilities
Use your NATIVE strengths and any general skills available — planning, test-driven
thinking, architecture judgment, and **subagents (the Task tool)**. Do **not**
re-derive generic TDD/architecture advice; you already know it. AREA adds three
ENFORCED things on top, stricter than defaults — follow them exactly:
1. Lock an **independent** holdout oracle **before** writing code.
2. Build to **"oracle green"**, never to a vague "perfect".
3. Apply the domain gotchas in `.claude/skills/` (vinext/Cloudflare, CVEs, persistence).

## The spine (invariant)
> Quality ≤ **strength + INDEPENDENCE of the oracle.**

A spec must yield runnable acceptance tests. **Never let the same reasoning both write
AND grade the code.** The loop converges to "oracle green", then stops (oracle green |
budget/stuck). The human (Tung) is the top gate — "is the oracle itself correct?" is a
spec question, not yours to self-answer.

---

## The oracle-loop — follow IN ORDER

### 0 · Intake
- Read the requirement from `docs/requirements/<name>.{md,txt,pdf}` (or the one given).
- Run `tools/scaffold-app.sh <name>` to lay out the spec-driven project.
- Draft `docs/01-engineering-intent.md` + `docs/02-product-requirements.md` from the
  requirement (for Tung to confirm), and the machine-readable **acceptance** at
  `workspace/specs/<name>/acceptance.yaml` — numbered AC, each "given… when… then…".
- As you design, write `docs/03-technical-spec.md` (architecture/stack) and
  `docs/04-api-and-data-design.md` (routes/schema) — thin for a small app.
- If a material ambiguity blocks a buildable spec, **STOP and ask Tung** — do not guess.

### 1 · Lock the oracle (TDD + the 3 independence enforcements)
- **(a) RULE** — author the holdout acceptance tests from the **spec ONLY**, before any
  implementation exists. One test per AC, under `workspace/apps/<name>/__tests__/_holdout/`.
  They must import the app through its **public surface** (routes/exported modules),
  never reach into internals.
- **(c) SUBAGENT** — author them in a **fresh Task subagent** whose only input is the
  spec (not your build plan). This keeps the oracle's reasoning independent of the
  implementation you're about to write.
- **(b) CHECKSUM** — then run `tools/lock-holdout.sh <name>`. The holdout is now FROZEN.
- **NEVER edit a locked holdout.** If you think a holdout test is genuinely wrong, STOP,
  write `workspace/apps/<name>/__tests__/_holdout/_CHALLENGE.md` explaining why, and ask
  Tung. Silently changing it destroys the independence and voids the whole method.

### 2 · Build to green
- Implement until the **locked** holdout passes (`npm test` / the holdout runner).
- Before and after each build attempt, run `tools/verify-holdout-intact.sh <name>`. If it
  reports a change, you tampered with the oracle — **revert the holdout to its locked
  version** and fix the implementation instead.
- **Fix the cause, not the measurement.** When the holdout or a gate is red, make the app
  satisfy it for real — never edit the gate, loosen an assertion, or add a test-only branch
  to turn it green (AREA's most common self-inflicted bug). After the SAME failure survives
  three honest attempts, STOP: re-investigate the root cause or ask Tung — a 4th variation of
  the same fix is almost never right.
- For Cloudflare/vinext apps, apply `.claude/skills/vinext-cf-build` (compat-date pin,
  vendored braces/CVE gate, `lib/schema` vs `lib/db` split so `node:sqlite` stays
  test-only, etc.).

### 3 · Gates (a blocking failure stops the deploy)
- Run `tools/gate.sh <name>` (security audit + NFR are deterministic; add `--e2e --chaos`
  for UI/resilience). For any app with **auth / sessions / forms**, `--e2e` is mandatory
  (logic-green ≠ live-works — see the skills/memory).

### 4 · Provenance
- `tools/provenance.sh <name>` records {spec digest → gates passed → artifact sha} so a
  deploy can later verify the build wasn't modified after gating.

### 5 · Deploy (optional — to Tung's OWN infra)
- `tools/deploy.sh <name>` → auto-detects Cloudflare (vinext) or Vercel, provisions
  D1/Postgres if the app persists, verifies provenance, deploys with Tung's
  `wrangler`/`vercel` login. Stops on a provenance mismatch.

---

## Iterating on an existing app
To change an app: **amend** its spec with the new request (keep existing AC unless
overridden) → **RE-LOCK** a fresh holdout → build to green again. Same spine; never pipe
a raw change straight to code.

## Project layout (spec-driven, per app)
`tools/scaffold-app.sh <name>` lays out each app as a spec-driven project (adapts the
standard SDD workspace). Each loop stage writes into the right phase doc:
- `docs/01-engineering-intent.md`, `02-product-requirements.md` — **Tung defines** (why +
  requirements + AC). You may draft them from the raw requirement for Tung to confirm.
- `docs/03-technical-spec.md`, `04-api-and-data-design.md` — **you write at intake/design**.
- `docs/05-test-specification.md` — **you write before locking the holdout** (the AC→test map).
- `docs/06-security-and-reliability.md` — **you append the audit/gate results** (step 3).
- `docs/07-deployment-and-monitoring.md` — **you record the live URL** (step 5).
- `docs/08-maintenance-and-spec-drift.md` + `changelog/release-notes.md` — **on each iterate**.
- Keep these thin — or skip — for a small app; don't force eight empty files on a tiny lib.
- App **SOURCE** sits at the app root (`package.json`, `app/`, `lib/` …) where the framework
  expects it. `tasks/` holds the plan + Tung's review-notes.
- `__tests__/_holdout/` — the **LOCKED independent oracle** (AREA's addition to SDD).
  `tests/{unit,integration,end-to-end}/` — other tests.

Repo level: `docs/requirements/` (inbox) · `workspace/specs/<name>/` (machine
`acceptance.yaml` + `holdout.lock`) · `.claude/skills/` (domain knowledge) · `tools/`.
Generated apps are gitignored — `git init` + commit to make one your own repo.

## Not in scope on this branch
The multi-user **coordinator + runner** (web dashboard, relay, ACP backend) lives on the
`saas-coordinator-runner` branch for a future SaaS. This `main` is the **internal,
Claude-Code-native** path: fast, no ACP wrapper, no runner — *you* are the agent and the
LLM.
