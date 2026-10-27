# AREA vs. the Secure Software Factory reference architecture

- **Assessed:** 2026-10-27, against `docs/software-factory.pdf` — *"The Secure Software
  Factory: A Reference Architecture"*, Agent Baseline v1, 13 Oct 2026 (Docker, Keycard,
  Barclays, Socket, Secure Theory). Prose and figures CC BY 4.0.
- **Scope of the assessment:** AREA `main` as of `5be44d2e` (~9.9k LOC in `area/`).
- **Status:** assessment accepted; backlog groups 1–2 implemented in the same change,
  groups 3–4 open.

## What the reference architecture says

A software factory needs **two layers of control**, and they are not substitutes:

| | Inside the loop | Outside the loop |
|---|---|---|
| Who decides | the agent reasons about what it *should* do | the runtime decides what it *can* do |
| Answers | "is this software acceptable?" | "what may this agent touch?" |
| Mechanism | inner/outer loop; verification + validation | four boundaries: sandbox, network, supply chain, identity & access |

> "an agent can stay within its scope and still ship a defect, and code can pass every
> test after its agent reached something it shouldn't have." — p.5

The reason the second layer cannot live inside the agent: *"because its decisions are
non-deterministic, understanding a constraint can't be the only way to enforce it"* (p.5).
The document then holds those four boundaries constant across three levels of autonomy
(human-orchestrated → workflow-orchestrated → agent-orchestrated), and what changes
between levels is how much of the enforcement infrastructure has to exist.

## Where AREA stands

AREA has built the **loops** half to a standard above what the document asks for, and the
**boundaries** half barely exists.

| Axis | Reference asks for | AREA today | Verdict |
|---|---|---|---|
| Inner/outer loop + verification | "verify against the standards" | checksum-locked independent holdout oracle, `_CHALLENGE.md` governance, 9 gates | **above the reference** |
| Validation (*did we build the right thing?*) | outer loop, evals, production signals | one `product` gate — advisory and fail-open; the holdout is derived from the spec, so a wrong spec goes green | weak |
| Sandbox | container/microVM per task, writes confined, no host access | host subprocess, `bypassPermissions`, no filesystem confinement, workspace defaults *inside* the repo (`area/paths.py:21`) | absent |
| Network | default-deny egress proxy, credentials attached outside the sandbox | none; `is_safe_http_url` exists only in `area/re/ui_capture.py:65` | absent |
| Supply chain | admission point, scan *before* install, version cooldown | `npm install --no-audit` (`area/build/nextjs.py:47`) and the build prompt tells the agent to install things itself; `npm audit` runs *after* install; no `--ignore-scripts` | low |
| Identity & access | per-agent identity, task-scoped short-lived credentials | 13-name env denylist (`area/engine/adapter.py:207`); no identity, no scope | low |
| Execution layer | start/stop agents, retries, kill switch | iteration caps and retries exist; **no kill switch**, no timeout on build/test/deploy subprocesses, `agent.close()` does not kill the process group | partial |
| Observability | one run id linking every boundary, tamper-evident, fail-closed | three unlinked id spaces; every write path is `except: pass`; the attestation lives *inside* the agent's own tree | low |

## Three findings of substance

### 1. AREA's records claim more than the code delivers

This matters more than the missing boundaries, because AREA's own spine is about not
trusting a grader that has an interest in the answer — and these records are AREA grading
itself.

- `area/cli.py` never passed `builder=`, so every attestation read
  `"area/openhands-acp"` (`area/provenance.py:106`) even for `--backend llm`.
- `gate_results = {g: True for g in gates}` recorded *selection*, not *outcome*: an
  advisory `visual` below threshold or a `cost` over budget was attested as `True`.
- No run could be reconstructed: model, backend, `--strict`, `--audit-level`,
  `--no-block-injection`, budget, iteration caps, the factory's own commit and the skills
  pack were all unrecorded. The document asks for the opposite (p.17, p.23).
- `docs/ARCHITECTURE.md` described three independence layers without saying *which agent*
  each one covers. The PreToolUse hook is wired from the repo's `.claude/settings.json`,
  so it guards a Claude Code session rooted in the repo — it is **not** installed into a
  generated app (`area/skills.py` copies skills, not settings), so it never applies to the
  autonomous ACP build agent. For that agent layer 1 is detect-and-revert, not prevent.

### 2. The enforcement points AREA already has were failing open

The document's invariant is *"an agent doesn't start if a required enforcement point is
down"* (p.9) and it names fail-closed authorization explicitly (AUT-06).

- An exception inside the provenance checker let the deploy proceed
  (`area/deploy/__init__.py`, `except Exception: print(... "skipped (warn)")`).
- `tools/deploy.sh` and the dashboard both hard-coded `--yes`, so the single human
  approval gate was bypassed by the factory's own tooling. Compare the
  *"Let's land #118"* incident (p.26).
- `--require-provenance` is `action="store_true"`, and `area/cli.py` passed that `False`
  through explicitly, so `require_provenance is None` was never true and
  `AREA_REQUIRE_PROVENANCE` was dead code on the `area deploy` path.
- D1/Postgres provisioning ran `wrangler d1 create` + `d1 execute --remote` and
  `vercel env add` / `psql -f` against production, documented "NON-FATAL by design",
  with failures swallowed — a high-impact action with neither approval nor a stop.
- `_confirm_fn` asked "Deploy … to Cloudflare PRODUCTION?" for Vercel deploys too.

### 3. The factory grades its own improvements

AREA's rule is *never let the same reasoning both write and grade*. Applied to AREA
itself: when a prompt, a skill or a gate threshold changes, nothing grades that change.

The document's answer (p.19): *"Use evals and run metrics to determine whether changes to
the factory's skills, tools, models, and workflows improve outcomes or introduce
regressions **before promoting them**."* AREA already has the seed — `obs.summary()`
reports `first_try_rate`, `retry_rate`, `avg_cost` per label — but it is a dashboard
number, not a gate on factory changes. This is the real outer loop and it is missing.

## Backlog

### Group 1 — make AREA tell the truth about itself · **done**
1. Attestation records the real `builder` (backend) and a `policy` block: model, backend,
   strictness flags, budget, iteration caps, the factory's git commit (with a dirty flag)
   and a digest of the skills pack.
2. Per-gate records carry `{ran, blocking, blocked}` plus `gatesNotRun`, so an advisory
   pass is no longer indistinguishable from a blocking pass. `_type` is now
   `area.slsa-like/v2`; `verify_provenance` still reads v1.
3. `docs/ARCHITECTURE.md` states which agent each independence layer actually covers.

### Group 2 — stop failing open · **done**
4. A provenance check that cannot run refuses the deploy.
5. `require_provenance` defaults to on; `AREA_REQUIRE_PROVENANCE=0` or
   `--no-require-provenance` is the explicit opt-out.
6. `tools/deploy.sh` no longer forces `--yes`; the dashboard must pass an explicit
   `confirm: true` for a deploy job.
7. A failed database provision blocks the deploy unless `--allow-provision-failure`, and
   the confirmation prompt names the provider and says a production database will be
   created/migrated.

### Group 3 — keep credentials out, and protect the factory · open
8. **Screen inputs, not just outputs.** `_SECRET_RE` (`area/verify/audit.py:28`) scans the
   built app. Nothing scans what comes *in*: Flow B copies an untrusted repo into
   `_sample/` → `_ui/` → the app, where the agent reads it, unscanned. This is the
   PocketOS shape (p.26) and the reference asks for input screening explicitly (p.7).
9. **`tools/verify-factory-intact.sh`.** The reference puts the factory's own code and
   configuration in the TRUSTED row: *"They change only through review, never during a
   run"* (p.6). AREA already invented the mechanism for this — `verify-holdout-intact.sh`
   checksums what must not change. Apply it to `area/`, `tools/`, `skills/`, and move the
   default workspace out of the repo.
10. **Timeouts and a kill switch.** No wall-clock cap on a build; `JobManager` has no
    cancel; teardown terminates the ACP process but not its process group, so
    agent-spawned trees can survive. `area/verify/perf.py:194` already has the
    `setsid`+`killpg` pattern to reuse. The cost gate is post-hoc and blocks a deploy; it
    cannot interrupt a thrashing run, which is a real money risk.
11. Wrap the agent env scrub around the whole conversation lifecycle, not only `run()`
    (`area/engine/adapter.py:255,291`). For the default ACP backend the scrub does hold —
    `_should_initialize_agent_on_send_message()` returns False for `ACPAgent`, so the
    spawn is deferred into `run()` — but for `--backend llm` agent init happens during
    `send_message`, outside the scrub. Two lines remove the question.

### Group 4 — a real outer loop · open
12. **A profile artifact.** An agent run's configuration is assembled from seven places
    (CLI flags → env → `build_agent` → per-module prompt literals → skills copy → memory
    injection → ad-hoc MCP config). AREA already has distinct agent kinds: re-extractor,
    spec-extractor, holdout-author, builder, product-reviewer, healer, researcher. The
    reference's profile is one versioned artifact per kind, which *"gives the outer loop
    one thing to improve, evaluate, and roll back"* (p.20).
13. **Evals for the factory.** Turn `obs.summary()` into the gate on changes to prompts,
    skills, models and thresholds. Depends on 12.

## Deliberately out of scope

Egress proxy, runtime authorization service, supply-chain firewall, model gateway,
per-task microVMs, short-lived task-scoped credentials and per-agent identity are
multi-tenant enterprise infrastructure. For a single-operator local factory they are the
wrong size, and the document itself notes the boundaries are *"security responsibilities,
not separate pieces of infrastructure"* (p.6).

They stop being optional the moment the `saas-coordinator-runner` branch becomes real.
Read as a checklist for that branch, the reference's Level 2 requires a fresh sandbox per
task, an authenticated profile, acting on behalf of a requester, revocation plus a kill
switch, records from every boundary linked by run, and component quarantine. Note that
`Dockerfile.runner` and `docs/RUNNER.md` already reference an `area/runner.py` that does
not exist on this branch — that is where this document should be read again from the top.

## See also

- `docs/software-factory.pdf` — the source document.
- [ADR 0003](adr/0003-oracle-loop-independence.md) — the oracle-loop; the "loops" half of
  the same idea.
- [ADR 0002](adr/0002-coordinator-runner-saas.md) — the coordinator/runner SaaS this
  assessment gates.
- [ARCHITECTURE.md](ARCHITECTURE.md) — the system map, including the independence layers
  corrected by item 3.
