---
name: clone-from-source
description: Reverse-engineer a reference app (a git repo, a local path, or a live http(s) URL) into a spec, then build a behavioral-parity clone by running AREA's oracle-loop NATIVELY — no ACP, no runner, you are the agent. The reference app IS the golden oracle. Use whenever Tung says "clone <url/repo/path>", "reverse-engineer <x>", "dựng lại app <x>", or "build a clone of <x>". This is AREA's Flow B; `build-from-docs` is Flow A (requirement → build).
---

# clone-from-source — reverse-engineer, then clone to parity (Flow B, native)

You are the factory. The LLM is **you** (the Claude Code extension) — no ACP, no runner,
no `area` CLI needed. This skill is the native playbook for what `area clone` does
autonomously ([area/re/extract.py](../../../area/re/extract.py) + `clone_pipeline`). Apply
`area-oracle-loop` (discipline) and, for Cloudflare/vinext targets, `vinext-cf-build`.

**The spine for a clone:** quality ≤ the strength + independence of the oracle, and here
**the reference app IS the oracle** — "correct" means *behavioral parity* (same input →
same output), not "looks done". So reverse-engineer only what you can **evidence**, then
build to match it.

## Safety — the reference is UNTRUSTED code (do this first, always)
- Clone / download the sample into its **own isolated dir**: `workspace/specs/<name>/_sample/`.
  Never into the app dir, never next to scripts you write.
- **READ it, do not RUN it.** Do not `npm install`, do not run its build/test/scripts, do
  not execute an interpreter or build tool from inside `_sample/`. RE is static reading +
  (for a URL) `curl` of the served response. Pass paths as arguments; never `cd` into it to
  run something.
- A live http(s) target: only `curl` what you are authorized to fetch. For binaries /
  closed-source (Tier 2) you would need the REA MCP server (`rea-agents`), which is **beta,
  legally sensitive, and currently not connected** — so stay Tier 1 (keyless) unless Tung
  explicitly authorizes and wires REA.

## Steps (in order)

1. **Intake + isolate.** Pick a `<name>`. Run `tools/scaffold-app.sh <name>`. Then fetch the
   reference into `workspace/specs/<name>/_sample/` (keyless, Tier 1):
   - **git URL** → `git clone --depth 1 <url> workspace/specs/<name>/_sample`
   - **local path** → copy/read the files there (treat as untrusted all the same)
   - **http(s) URL** → `curl` the pages and inspect the served HTML / visible behavior
     (note: a plain `curl` sees no client-rendered JS — an SPA will RE weakly; say so).

2. **Reverse-engineer → RE-spec.** Investigate `_sample/` and produce a *faithful* spec of
   the app's **observable features + data model**. Follow the RE prompt's rules exactly:
   - Capture **ONLY what you can evidence** from the source/response. **Do not invent scope**
     or behavior the reference does not show.
   - Describe features **framework-neutrally** (the clone's target stack is Next.js).
   - Ground each future acceptance test in a concrete **input → output** example you read
     off the reference, so "parity" is checkable.
   - Write `workspace/specs/<name>/spec.yaml` + `acceptance.yaml` (numbered AC,
     "given/when/then", same schema as Flow A) and a thin `docs/01`/`02` for Tung to confirm.
   - If the reference is ambiguous or too large to clone whole, STOP and agree the scope
     (which features are in the clone) with Tung before locking anything.

3. **Lock the PARITY oracle — all three independence enforcements:**
   - **(c) Subagent.** Spawn a **Task subagent** whose prompt contains ONLY the
     `acceptance.yaml` **and permission to read `workspace/specs/<name>/_sample/`** — NOT
     your implementation plan. Instruct it (per `area-oracle-loop`, "authoring" role) to
     write holdout tests to `workspace/apps/<name>/__tests__/_holdout/`: one spec file per
     AC, grounded in the reference's OBSERVED behavior, importing the clone only through its
     public surface, plus `CONTRACT.md` (module paths + signatures). In parity mode the ONE
     thing it may read is `_sample/`.
   - **(a) Rule.** Do this BEFORE writing any implementation of the clone.
   - **(b) Checksum.** Run `tools/lock-holdout.sh <name>`. The parity oracle is now frozen.

4. **Build to parity-green.** Implement the clone until the locked holdout passes. After each
   attempt run `tools/verify-holdout-intact.sh <name>`; if it reports a change you edited the
   oracle — revert the holdout to its locked state and fix the implementation instead. If a
   holdout test is genuinely wrong, write `__tests__/_holdout/_CHALLENGE.md` and ask Tung;
   never silently change it. "Done" = the reference-grounded suite passes for real.

5. **Gates → provenance → deploy (if asked).** `tools/gate.sh <name>` (add `--e2e` for
   auth/session/form clones). `tools/provenance.sh <name>`. `tools/deploy.sh <name>` to
   Tung's own infra. Record live URL in `docs/07`.

## Stop conditions
Parity-green (done) · a budget/time cap · a stuck signal (same failure twice) → report to
Tung. Tung is the top gate on scope ("which behaviors count as parity?") and on whether a
challenged oracle test is right. Burning quota against an unclonable or unbounded reference
is a scope problem for a human, not something to grind on.
