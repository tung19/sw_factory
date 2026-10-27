# AREA vs. the Secure Software Factory reference architecture

- **Assessed:** 2026-10-27, against `docs/software-factory.pdf` — *"The Secure Software
  Factory: A Reference Architecture"*, Agent Baseline v1, 13 Oct 2026 (Docker, Keycard,
  Barclays, Socket, Secure Theory). Prose and figures CC BY 4.0.
- **Scope of the assessment:** AREA `main` as of `5be44d2e` (~9.9k LOC in `area/`).
- **Status:** assessment accepted; the whole backlog (groups **1–4**) is implemented.

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

### Group 3 — keep credentials out, and protect the factory · **done**
8. **Screen inputs, not just outputs.** `area/screen.py` (stdlib leaf) redacts
   credentials in every copy that reaches the agent — `_sample/` → `_ui/` → `.area-ui/`,
   uploads, and AI-DLC artifacts — while `_sample/` itself stays byte-exact and is
   scanned-and-reported instead, because it is the evidence the clone was
   reverse-engineered from. Counts land in `UiEvidence` and the manifest; every
   redaction is printed, since a false positive quietly corrupting a clone is worse
   than a visible one. *Do not reuse `area/verify/audit.py:28` for this:* that pattern
   is written for grep and its `[[:space:]]` is a POSIX class Python's `re` accepts
   silently and misreads, so a screener built on it would protect nothing.
   `tests/test_screen.py` pins that trap and asserts both engines against one corpus.
9. **`tools/verify-factory-intact.sh`** — modeled on `verify-holdout-intact.sh`:
   `snapshot` before a build, `verify` after, covering `area/`, `tools/`, `skills/` and
   `.claude/settings.json` (bytecode excluded). A change mid-run **fails the build**
   before anything is attested, and the lock lives in the OS temp dir, not the
   workspace the agent can write. The default workspace was deliberately left alone —
   relocating it would strand existing apps — so `area doctor` now warns when it sits
   inside the repo, and the checksum is the real protection.
10. **Timeouts and a kill switch.** `command_verifier` (the `npm install && build &&
    test` call), the holdout runner, and every wrangler/vercel/psql invocation are now
    capped; a timeout is reported as an ordinary failure so the loop can feed it back
    rather than crash. `run_until` has a whole-loop wall clock (1h default ≈ 4× the
    worst build measured). `area._util.kill_process_group` — promoted from
    `perf._stop`, now the single implementation — kills the process GROUP, and
    dashboard jobs start their own session so `DELETE /api/jobs/{id}` (plus a stop
    button) can actually stop one. Verified on real forked trees: no orphans.
11. The agent env scrub now wraps the whole exchange via `_send_and_run`, with a drift
    guard asserting `send_message` is called from exactly one place. For the default
    ACP backend the old scrub did hold — `_should_initialize_agent_on_send_message()`
    returns False for `ACPAgent`, so the spawn was already deferred into `run()` — but
    for `--backend llm` init happens during `send_message`, and the posture should not
    depend on which backend is in use.

### Group 4 — a real outer loop · **done**
12. **A profile artifact** — `profiles/<kind>.yaml` + `area/profile.py`, one per kind of
    agent AREA runs. The real count is **16, not the 7 estimated above**: the obs log's
    label families are the ground truth, and they include distinctions worth keeping —
    `holdout-author` (writes the oracle) and `holdout-fixer` (fixes code against it) are
    separate profiles in the same module, because that separation *is* the spine.
    Each profile holds only what it controls or identifies — the obs label globs that
    attribute a run to it, the prompt symbols whose **source is hashed**, the skills
    flag, and `agent_iters`/`budget_usd`/`max_iters` defaults applied when a caller
    passes nothing (a CLI flag still wins). Prompts stay in Python: they are
    interpolated f-strings with real branching, so hashing their source buys the same
    attribution as a lossy rewrite into templates. Every `defaults` value ships as
    `null`, so adopting profiles changed no behaviour — tuning one is now a one-file,
    reviewable, rollback-able edit, which is the reference's whole point (p.20).
    Per-kind model selection (model tiering, `PLAN.md` §10 P5) is the obvious next use
    of this seam and is deliberately not claimed yet.
13. **Evals for the factory** — `area/evals.py` + `area evals [--check] [--strict]`,
    also `make evals`. `obs.log_run` now stamps `(profile, profile_digest)` on **every**
    run from one place, so all 19 agent call sites are attributed without being touched.
    `area evals` grades each kind's **current** version against the previous one on
    first-try rate, pass rate, avg attempts and avg cost (cost relatively, so a cheap
    stage doubling is caught). A regression fails `--check`; so does a profile file that
    cannot load, because that silently stops attributing runs. "Not enough data" passes
    unless `--strict` — a gate that cannot measure must not pretend it did.
    It is **not** in `_GATE_ORDER` and a test pins that: the gate set decides whether an
    *app* may ship, evals decides whether a change to the *factory* may be promoted.
    Honest limit: the 110 runs recorded before profiles existed carry no digest and are
    reported as `unattributed` rather than folded into a baseline — we do not know which
    prompt produced them, so every kind starts at "no attributed runs yet".
    That report also surfaced something worth acting on: **5 of the 16 kinds have never
    run** in 110 recorded runs. Triaged 2026-10-27, and each profile's `notes` now
    records its reason — because "never ran" meant two very different things:
    - **`spec-reviewer` was a BUG, now fixed.** The pipeline guard was
      `clarify and spec_review`, so `--no-clarify` silently switched the *independent*
      spec reviewer off as a side effect — and `--no-clarify` is exactly what you pass
      for an unattended run, so the review was disabled precisely when nobody was
      watching. It is now gated on `spec_review` alone: `clarify` decides whether the
      build STOPS, `spec_review` decides whether the reviewer RUNS. Its findings matter
      either way, since they land in `assumptions.yaml`, which `area/reality.py` prints
      and `provenance._MATERIALS` attests. Evidence it truly never ran: 5 spec/intake
      runs happened *after* the reviewer shipped and obs recorded zero `spec-review`
      runs — conclusive because `ask_cli` logs in a `finally` and so records failures
      too.
    - **The other four are genuinely un-invoked, for four different reasons**, all now
      written into their profiles: `holdout-fixer` is unreachable on the default path
      (`--tdd` removes the non-TDD `verify` gate that owns it); `holdout-readjudicator`
      needs a `_CHALLENGE.md`, which has never happened; `product-reviewer` is opt-in,
      and its own promotion rule is circular — it may only become blocking after its
      false-positive rate is measured, which cannot happen until it runs;
      `researcher`'s live dogfood is deferred pending a funded run. All four are covered
      agent-free by tests, so what is missing is live exercise, not logic.

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
