---
name: build-from-docs
description: Build (or iterate) an app from a requirement in docs/requirements/ by running AREA's oracle-loop natively — extract a spec, author an INDEPENDENT holdout oracle in a subagent and lock it, build to oracle-green, run the deterministic gates, then deploy to your own infra. Use whenever Tung says "build the app in docs/requirements/<x>" or "iterate <app>: <change>".
---

# build-from-docs — run the AREA oracle-loop natively

You are the factory. Follow the root `CLAUDE.md` spine. This skill is the concrete
playbook of tool calls. Apply `area-oracle-loop` (discipline) and, for Cloudflare/vinext
apps, `vinext-cf-build` (gotchas). The LLM is you (the Claude Code extension) — no ACP,
no runner.

## Steps (in order)

1. **Intake.** Read `docs/requirements/<name>.{md,txt,pdf}` (extract PDF text first). Run
   `tools/scaffold-app.sh <name>` to lay out the spec-driven project. Draft
   `docs/01-engineering-intent.md` + `02-product-requirements.md` (for Tung to confirm) and
   the machine `workspace/specs/<name>/acceptance.yaml` (numbered AC, "given/when/then").
   Write `docs/03-technical-spec.md` + `04-api-and-data-design.md` as you design (thin for
   small apps). If a material ambiguity blocks a buildable spec, STOP and ask.

2. **Lock the oracle — all three independence enforcements:**
   - **(c) Subagent.** Spawn a **Task subagent** whose prompt contains ONLY the spec +
     acceptance.yaml (NOT your implementation ideas), instructing it to write the holdout
     acceptance tests to `workspace/apps/<name>/__tests__/_holdout/` — one spec file per
     AC, importing the app only through its public surface, plus a `CONTRACT.md` listing
     the module paths + signatures the tests import. This keeps the oracle independent of
     the code you will write.
   - **(a) Rule.** Do this BEFORE writing any implementation. Never edit a locked holdout.
   - **(b) Checksum.** Run `tools/lock-holdout.sh <name>`. The holdout is now frozen.

3. **Build to green.** Implement the app until the locked holdout passes. After each
   attempt run `tools/verify-holdout-intact.sh <name>`; if it fails you edited the oracle —
   revert the holdout to its locked state and fix the implementation instead. If a holdout
   test is genuinely wrong, write `__tests__/_holdout/_CHALLENGE.md` and ask Tung — do not
   silently change it.

4. **Gates.** `tools/gate.sh <name>` (security audit + NFR). Add `--e2e` for any app with
   **auth / sessions / forms** — write one Playwright spec per AC under `e2e/`, then it
   runs them (logic-green ≠ live-works).

5. **Provenance.** `tools/provenance.sh <name>` (attests spec→gates→artifact).

6. **Deploy (if asked).** `tools/deploy.sh <name>` → your Cloudflare/Vercel.

As you go, record each artifact in its phase doc: `05-test-specification.md` (before
locking the holdout), `06-security-and-reliability.md` (audit results, step 4),
`07-deployment-and-monitoring.md` (live URL, step 6), and `08-maintenance-and-spec-drift.md`
+ `changelog/release-notes.md` on every iterate. Keep them thin for small apps.

## Iterate an existing app
Amend `workspace/specs/<name>/spec.md` with the change (keep existing AC unless overridden),
then redo steps 2→4 (fresh subagent-authored holdout, re-lock, build to green, gates).
Never pipe a raw change straight into the code.

## Stop conditions
Oracle green (done) · a budget/time you set · a stuck signal (same failure twice) → report
to Tung rather than thrash. Tung is the top gate on whether the oracle itself is right.

## Progress ledger (resume after a context reset)
Record each milestone as it goes GREEN with `tools/task-done.sh <name> <milestone> -- <verify-cmd>`
(e.g. `holdout-locked`, `build-green`, `gate-audit`, `provenance`). The script appends to
`workspace/apps/<name>/.area/progress.md` only when the verify command exits 0 — the ledger
records proven state, not intentions. On resume, run `tools/task-done.sh <name> --show` first and
SKIP any milestone already recorded rather than re-doing it.
