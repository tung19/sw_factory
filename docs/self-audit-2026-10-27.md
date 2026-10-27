# Self-audit — 2026-10-27

Independent audit of this repo, run the way AREA's own spine demands: **I wrote most of
the code audited here, so I am not the only grader.** Four read-only subagents audited
in parallel (correctness/false-greens · security · architecture & test quality ·
docs-vs-code truthfulness), each briefed to distrust the prose, because this repo's
proven failure mode is records overstating the code.

Every finding below I then **re-verified myself** against source or by running it — one
subagent had earlier reported a "critical" hole that did not exist. Findings a subagent
reported but I have not personally confirmed are kept in a separate section and are
labelled as such.

Tree: `feat/saas-forward-port` @ `c1d9774b`. Suite at audit time: **657 passed**, mypy
strict clean (71 files), ruff clean.

---

> **Status:** S1, S2, S3, S4 are **fixed** — S1+S2 in this branch
> (`fix/gate-grades-what-it-prints`), S3 on `feat/saas-forward-port` where the code
> lives. H1–H6 and M1–M5 are open. Each fix section below records what changed.

## Severity S — a gate says PASS when it should say FAIL

### S1 · `audit` prints `❌ BLOCK` and then returns PASS (default posture) — FIXED
`area/verify/audit.py:186-235`. Control flow: a tier-2 injection finding sets
`tier2_block=True`, which skips the early-PASS branch and enters the fix loop — but the
loop's `oracle` is **tier-1 only** (`_check()`). Tier-1 is already green, so `passed=True`
on attempt 1, and the only tier-2 re-check is guarded `if passed and strict and …`.
With the default `strict=False` tier-2 is never re-measured.

Observable: an app with `dangerouslySetInnerHTML` / `eval(` / interpolated SQL prints
`❌ BLOCK <file>:<line>` for each sink, then prints `audit: ✅ PASS`. Provenance then
records `audit` as `{blocking: true, blocked: false}` — i.e. "enforced, nothing found".

This was **remediated finding #17** ("audit injection-class blocks-by-default"). The
remediation added the decision (`_blocking_findings`) but never moved the measurement
into the oracle, so the claim has been false since it was made.

### S2 · `area/screen.py` misses the commonest real credential shapes — FIXED
Reproduced by me, 4 for 4, against the shipped module:

| input | findings | secret still in the output |
|---|---|---|
| minified JS with `process.env` elsewhere on the line | 0 | `ghp_…`, `xoxb-…` |
| attacker plants the literal `AREA-REDACTED` in the file | 0 | `ghp_…` |
| two secrets on one line | 2 | the 2nd one (reported, not redacted) |
| `process.env.X \|\| "postgres://admin:<pw>@host/db"` | 0 | the password |
| control: plain one-line assignment | 1 | none |

The first and last rows are the normal shapes in a bundled reference app — i.e. exactly
the Flow B input this module was written to screen. The `AREA-REDACTED` row is worse than
a miss: the marker is attacker-controllable, so planting it disables screening for the file.

**Fix:** both root causes were scope errors. Line-scope exclusion became **statement**
scope (`_statement_at`, bounded by the nearest separator, ≤120 chars) and now applies only
to `_ASSIGNMENT`, where "it came from the environment" is a real alternative reading — a
vendor pattern matches a literal credential, which no env lookup can produce, so nothing
nearby excuses it. The `AREA-REDACTED` marker is off the exclusion list entirely;
idempotence comes from `_EXCLUDE_VALUE` matching the value *we* wrote, not text an input
can choose, which also fixes the "first redaction excuses the second" case.

Smoked on a **real** 516KB minified bundle (`next/dist/compiled/terser/bundle.min.js`,
one line, containing `process.env` — the old code returned zero findings on it): the
planted token is now found and removed.

**Also calibrated against real input, which changed the fix.** Screening 100 real files
from a built app produced **15 findings, every one a false positive** of the same shape —
an unquoted JS expression (`token = creditTokenParam`, `privateKey: r.ECPrivateKey.decode`).
Redaction rewrites the copy the agent reads, so each would have silently corrupted
third-party source — the harm this module's own docstring says to avoid. `_CODE_VALUE` now
excludes unquoted member expressions and camelCase identifiers, taking the same 100 files
to **1** (a PascalCase schema name, in `node_modules`, which `scan_tree` skips anyway). The
rule is deliberately not extended to PascalCase: that would also exclude a real password
like `Pr0dPassw0rd`. Both the four shapes and this calibration are now the corpus in
`tests/test_screen_corpus.py`.

### S3 · `job_argv` deploys with no human gate — and a test pins it — FIXED
`area/net/protocol.py:87` (`["--deploy", "--yes"]`) and `:96` (`["deploy", name, "--yes"]`).
This re-opens the exact fail-open closed in `area/web/jobs.py` (`_deploy_approval()`
requires `confirm: true`), and `tests/test_net.py` asserts `"--yes" in d`, so the suite
defends the hole. Shipped by **PR #36** (the SaaS forward-port), opened today.

**Fix** (on `feat/saas-forward-port`, where the code lives): the approval has to travel in
the request (`confirm: true`) and its absence refuses the job — `runner._exec_job` already
turns the `ValueError` into a failed job the UI shows. The local dashboard was already
sending `confirm:true` behind a real `confirm()`; the coordinator UI was not, and now takes
the same approval before it sends.

### S4 · the locked oracle can report green with zero locked tests executed — FIXED

Promoted from the unverified list and **reproduced end to end against real vitest
5.0.5**, because it defeats the spine rather than a gate.

vitest's positional argument is a case-insensitive **substring** match on the path
relative to the project root, and `filterFiles` only narrows what `include`/`exclude`
already globbed. So one line in the builder-owned `vitest.config.ts`:

```ts
exclude: ['**/node_modules/**', '**/__tests__/_holdout/**']
```

evicts the locked suite *before* filtering, while a decoy directory whose name merely
**contains** the locked path (`__tests__/_holdout_decoy/`) is still collected by the
oracle's own `npx vitest run __tests__/_holdout` (`holdout.py:352`).

Measured, not argued — a throwaway app with one **failing** locked test, a 3-test decoy
and that one config line:

| | |
|---|---|
| the real locked test (failing) | **never ran** |
| 3 decoy tests | ran, passed |
| exit code | **0** |
| `no test files found` banner | absent |

Every other guard was satisfied, which is what makes this the worst finding in the
audit: nothing was tampered with, so the checksum lock matched, the PreToolUse hook had
nothing to block, and `assert_vitest_ran` saw 3 ≥ 1 passes with a valid summary. The
`_runners.py` docstring already named this threat class ("the app's vitest config is
authored by the builder and is NOT locked") and guarded the **count** but never **which
files ran**.

**Fix:** the oracle now runs `--reporter=default --reporter=json
--outputFile.json=<random path outside the app>` and asserts, via
`assert_locked_files_ran`, that every file in the lock appears in the runner's own report
of what it executed. It is deliberately an assertion about **outcome**, not about
configuration, because configuration is what the builder controls. A missing or
unreadable report FAILS — the whole point is to stop trusting a green exit code. CLI
`--exclude` was checked as an alternative and rejected: vitest documents it as
*"additional* file globs", so it cannot neutralise a malicious config exclude (verified
by running it).

Verified on three cases through the real oracle: **attack blocked · honest-green still
green · honest-red red for the right reason** (not via "ORACLE DID NOT RUN"). That third
case earned its place — a first version of the fix passed the locked lock keys against
the app root instead of the holdout directory, which blocked the attack *and* every
honest build. Only the end-to-end run caught it.

---

## Severity H

### H1 · The autonomous builder is shipped a stale skills pack — FIXED
`area/skills.py:15` → `SKILLS_DIR = <repo>/skills`, and `area/provenance.py` `skills_digest()`
hashes the same directory. `skills/vinext-cf-build/SKILL.md` is **70 lines (2026-10-19)**
with **zero** mentions of `cf-fix`; `.claude/skills/vinext-cf-build/SKILL.md` is
**105 lines (2026-10-22)** with 7, carrying the whole "`area cf-fix`/`cf-clone` automates
§1–§4" rewrite. Only the interactive agent reads `.claude/skills/`. So the CF automation
the changelog records as shipped never reaches the build agent, and the attestation
digests the stale copy. (`area-oracle-loop` is byte-identical in both trees — the drift
is specific to the CF skill.)

**Fix:** the maintained text is now shipped, and `tests/test_skills_in_sync.py` makes the
drift impossible to merge unnoticed — any skill name present in **both** trees must be
byte-identical, and the interactive-only set (`build-from-docs`, `clone-from-source`,
which drive the factory and mean nothing inside a generated app) is declared, so adding
one is deliberate. Same invariant CI already enforces for the two copies of the
coordinator UI, kept as a test so `make check` catches it locally too.

Two things were checked before copying rather than assumed. First, whether the newer text
is even appropriate for the in-app agent, since it leads with `area cf-fix <app>` — a
factory command, and the `area` CLI is only on an in-app agent's PATH when the venv
happens to be activated. It is appropriate: the rewrite is a superset that keeps the
mechanism and says so explicitly, and §3/§4 give both the automated and the manual route.
Only §1 had lost its manual route, so that sentence is restored. Second, that
`skills_digest()` hashes the shipped tree and is actually sensitive to its content —
verified by probe, and now pinned by a test.

Only **1 of 16** profile digests changes as a result, which is correct: `builder` is the
only profile declaring `skills: all`, and `install_skills` is called from exactly one
place (`area/build/nextjs.py:267`, the builder's path).

### M6 · 15 profiles declare `skills: none` but their agents can still read the pack

Found while fixing H1; recorded rather than silently changed, because the fix is a design
choice. `install_skills` copies the pack into `<app>/.claude/skills/` during the build and
the files **stay there**. Every agent that later runs with the app as its working directory
— `audit --fix`, the chaos author, the e2e author — is a Claude Code session in that
directory, so it discovers those project skills too, while its profile says `skills: none`.

Consequence for `area evals`: a skill edit changes only `builder`'s digest, so those kinds
are judged as unchanged across a factory change that can in fact alter their behaviour.
Either the profiles should record the inherited pack (which makes a skill edit invalidate
them too — arguably right, possibly over-broad, since the chaos author has no use for the
CF skill), or the nuance belongs in each profile's notes. Deciding that is Tung's call.

### H2 · `npm install` / build / test run with cloud tokens present — FIXED
`area/engine/adapter.py`: the scrub is inside `_send_and_run`, but `run_until` calls
`verify()` at top level (`run_until+39`, `+60`). `verify()` is what runs the generated
app's `npm install && build && test` — arbitrary postinstall scripts from an
agent-authored `package.json`, with the parent environment intact.

**Fix — two mechanisms, because there are two shapes.** `command_verifier` launches its
own subprocess, so it now hands the child a filtered `env=scrubbed_env()`, which needs no
global mutation: nothing else in this process ever observes the credentials missing, not
even for the duration of a build. A `Verifier` is an *arbitrary callable* that may launch
subprocesses inheriting `os.environ` (the holdout oracle does exactly that), so
`run_until` wraps both `verify()` call sites in `_scrubbed_agent_env()`.

Swept the rest of the same class while here: the holdout oracle's own `subprocess.run`,
and the three per-module `_env()` helpers (`verify/nfr.py`, `verify/perf.py`,
`build/cf_scaffold.py`) which were each `dict(os.environ)` and supplied the env for
`npm run build`, `npm run <script>` and the app server. The two remaining
`subprocess.run` calls in `holdout.py` run **AREA's own** `verify-holdout-intact.sh`, not
generated code, and are left alone.

Only the named keys are dropped, which is what makes this safe to apply to the build
itself: `PATH`, `HOME` and the npm/node configuration survive, verified by a real
subprocess that resolves `npm` and reports zero matching variables.

**Also confirmed and fixed here: `ask_cli` was unscrubbed** — one of the subagent claims I
had left in the unverified list. `area/engine/adapter.py:182` spawned `claude -p`, an
agent session *with tool access*, prompted with content AREA did not write, and passed no
`env=` at all. It authenticates from the Claude Code login in `HOME`, never from a key in
the list, so the scrub costs it nothing.

### H3 · `perf` fails open on a committed budget — FIXED
`area/verify/perf.py`: `if not metrics: … return True` executes **before** `blocking` is
consulted. `area/verify/nfr.py:173-176` does the same situation correctly (committed +
unmeasured → `return False`, "not silently passing"). The repo's own rule is nfr's.

**Fixed in the same change as H2, because the two are coupled, not because it was
convenient.** Scrubbing `perf`'s environment makes an unstartable server *more* likely, and
the commonest reason `perf` cannot measure is exactly that — so leaving the fail-open in
place would have converted a server that fails to start into a silent pass on a committed
budget. Both fail-open paths now respect `blocking`: an unmeasurable committed budget
fails loudly, and so does a measurement that matched no budgeted metric. Without a
committed `perf.yaml` and without `--strict` it still skips, so a default nobody asked for
cannot block a build.

### H4 · `run_once` records every run as a pass — FIXED
`area/engine/adapter.py:302` — `passed=True` is a literal. `area evals`, the group-4 gate
on changes to the factory's own prompts and thresholds, grades on `pass_rate` from this
ledger. The gate is reading a constant.

Worse than a wrong value: `run_once` takes **no Verifier** — it sends one message and runs
the agent to completion — so the field asserted a verdict nobody measured. Measured
damage in the live ledger: **110 runs, 109 saying `passed=True`, exactly one `False`.**

**Fix:** `run_once` no longer passes `passed` at all. `obs.log_run` already defaults it to
`None` and `evals.metrics` already excludes unjudged runs ("None where it cannot be
computed — never 0"), so the honest ledger needed only the lie removed. A caller that
does verify afterwards must log its own verdict; it must not be inferred from "the agent
finished". The 110 legacy runs are untouched and remain excluded from every baseline (they
carry no profile digest); `evals.py` now records *why* they must not be rescued as one.

### H4b · `area evals` compared versions that ran different work — FIXED

Found while fixing H4, and the reason H4 alone would not have been enough. `compare()`
took every run of version A and every run of version B and compared the aggregates, with
no regard for *which task* each run was on. A prompt that looks better may simply have
drawn easier tasks.

This is exactly what Google Research's Harness² controls for in its "probe" step — it runs
a candidate harness **on the same task under matched model and environment settings**
([arXiv:2610.14224](https://arxiv.org/abs/2610.14224)). Adopting that one idea, and
nothing else from it: Harness²'s core trick is refinement *without ground-truth
verifiers*, which is the opposite of AREA's spine.

**Fix:** a version is now graded only on the tasks **both** versions ran, keyed on the app
name `obs.set_app()` stamps. With no shared task the verdict is `unpaired` and nothing is
certified — deltas are still printed, labelled confounded, because a regression is worth
seeing even when it cannot be attributed. `unpaired` outranks `insufficient-data` on
purpose: "they did different work" is structural, and reporting "too small a sample" would
invite someone to fix it by collecting more unpaired runs, which can never make the two
comparable. `evals/tasks.yaml` declares the fixed A/B set (the three apps that already
have independent locked oracles, so "did it work" is not a judgement call), and
`area evals --tasks` prints it; `--any-task` opts out.

### H5 · "The builder can never edit the oracle (hook-enforced)" — three unqualified claims — FIXED
`README.md:44`, `SECURITY.md:72`, `docs/CASE-STUDY.md:60`. `area/skills.py` installs
skills only — **no `.claude/settings.json`**, so no PreToolUse hook exists in a generated
app. `docs/ARCHITECTURE.md:113-118` already states this correctly ("Covers **A only**"),
and `SECURITY.md:19-21` contradicts `SECURITY.md:72` in the same file. The CASE-STUDY run
making the claim is `--target plain --tdd` — precisely the autonomous agent the hook never
reaches. Real enforcement there is detect-and-revert + the checksum, which is weaker and
post-hoc.

**Fix — the docs, deliberately, and not the code.** The obvious "stronger" fix is to
install a `.claude/settings.json` into each generated app so the claim becomes true. That
would have produced FAKE enforcement, and the repo's own comment in `.claude/settings.json`
says why: a project hook runs only once the user **approves** it in Claude Code, and the
command **fails open** when the guard script cannot be located. `tools/hooks/guard_holdout.py`
lives in this repo, not in a generated app (verified: no generated app has either file),
so `CLAUDE_PROJECT_DIR` pointing at the app would find nothing and allow every edit —
while the docs would now be entitled to claim a hook. That is the exact failure mode this
audit exists to catch, so the claim was corrected instead.

Five sites corrected (`README.md`, `SECURITY.md`, `CONTRIBUTING.md`, `docs/CASE-STUDY.md`,
`docs/adr/0003`), each now naming **which layer covers which agent**. The honest sentence
is stronger than it was when this audit was written, because S4 landed in between: the
enforcement for the autonomous agent is the checksum lock **plus** the oracle requiring
the locked files to appear in the runner's own report of what it executed.

### H6 · Stored-XSS sink on the deploy-capable dashboard — FIXED

### H6 · Stored-XSS sink on the deploy-capable dashboard
`area/web/jobs.py:27` matches `…\.(?:workers|pages)\.dev\S*` — the `\S*` tail is unbounded.
`area/web/static/index.html:632` and `:665` interpolate that value into `href="${j.url}"`
inside `innerHTML` **without `esc()`**, while escaping the adjacent name. A build-log line
is enough to inject; in Flow B the log carries output from an untrusted reference.

---

## Severity M

- **M1 · `SECURITY.md:43` says "*every* agent/build/provider subprocess has a wall clock"** —
  four do not: `area/verify/nfr.py:106` (the full `--nfr-build`) and
  `area/build/cf_scaffold.py:100,109,296` (incl. `npm run build:cf`, the fallback build).
  The deploy CLIs genuinely are capped; the sentence overstates to "every".
- **M2 · `tools/gate.sh` silently ignores `--chaos`** — `tools/gate.sh:11` parses only
  `--strict|--e2e`, and the script runs no chaos gate at all, while `CLAUDE.md` step 3
  instructs the builder to pass `--e2e --chaos`. The factory's master rule set names a
  flag its own tool drops.
- **M3 · The showcase "gate evidence" is a pre-fix artifact** —
  `examples/taskboard/SPEC/provenance.json` is `area.slsa-like/v1`, `builder:
  "area/openhands-acp"` (the hardcoded literal the changelog says was fixed), and
  `gates: {holdout_tdd: true}` — one gate, no `{ran,blocking,blocked}`, no `policy`.
  `docs/CASE-STUDY.md:72-79` tables audit/nfr/perf/e2e/chaos as ✅ and `README.md:24-26`
  calls the directory "the gate evidence".
- **M4 · Stale counts** — `569 tests` in `CONTRIBUTING.md:26` and `docs/UPGRADE-PLAN.md:12`
  vs **657**; `docs/ARCHITECTURE.md:52` "the 9 gates below" over an 8-row table (`visual`
  has no row); `UPGRADE-PLAN.md:47` "8 gates"; `PLAN.md:101,201` "59/56 modules" vs 71.
- **M5 · `scripts/run-runner.sh:38` execs `area runner`, which does not exist** — zero
  `add_parser("runner")`, zero `_HANDLERS` entry. A documented `curl … | bash` path that
  cannot run. **Branch-scoped:** `area/runner.py`, `area/net/*`, `coordinator-cf/` and
  these scripts are absent from `main` — the "not on this branch" banners are accurate
  for `main`, and it is commit `c1d9774b` (today's forward-port) that shipped the data
  plane here without updating them.

---

## Reported by a subagent, NOT yet verified by me

Listed so they are not lost; each still needs a first-hand check before it is treated as
real.

- Nothing re-verifies the locked oracle after `--tdd`: the `verify` gate is removed while
  `audit --fix` / `chaos` / `e2e` then run agents in the app directory.
- `readjudicate` may re-lock tampering.
- `tools/verify-factory-intact.sh` lives in the tree it protects, with its lock in
  `TMPDIR`, writable by the agent.
- `.area/provenance.json` is forgeable (already documented honestly in the module docstring).
- `build_app` is at 0% test coverage, guarded only by a source-text proximity assertion.

## Verified sound (independently re-checked, trustworthy)

- The 9-gate registry is real and pinned (`cli.py:33` + `tests/test_gate_registry.py`).
- `profiles/*.yaml`: 16 files, all load, **zero** missing prompt sources, every label the
  code emits — including the f-string families — resolves to exactly one profile.
- Obs ledger: 110 runs, and exactly the 5 kinds named in the handoff have never run.
- A locked oracle is not re-authored (`holdout.py:283-298`: reuse on intact, raise on
  tampered); `spec-reviewer` survives `--no-clarify` (`pipeline.py:214-223`).
- `e2e` is forced before deploy for auth apps; the `visual` gate is auto-added when `_ui/`
  was captured — the "built but never ran" defect is genuinely fixed.
- Provenance v2 reports a real builder, per-gate `{ran,blocking,blocked}`, `gatesNotRun`
  and `policy`, with `None` where undeterminable.
- Deploy fails closed (tri-state `require_provenance`, `tools/deploy.sh` no longer forces
  `--yes`) — which is what makes S3 a regression rather than a known gap.
- `examples/taskboard`'s holdout checksums match its committed `holdout.lock` byte-for-byte.

---

## Scores

| Dimension | Score | Why |
|---|---:|---|
| Oracle independence (the spine) | 7/10 | Design is strong and layer 1+3 are real; but the `audit` gate's oracle does not measure what the gate prints, and layer 2 does not exist for the autonomous agent three docs say it covers. |
| Gate honesty ("green" means green) | **5/10** | Three confirmed false-greens: S1, H3, H4. |
| Attestation / provenance | 7/10 | v2 genuinely tells the truth; loses points for digesting the stale skills tree and for being forgeable-by-design. |
| Boundaries (sandbox · network · supply chain · identity) | 3/10 | Deliberately out of scope until `saas-coordinator-runner` — but H2 and S2 are in-scope regressions inside that gap. |
| Engineering hygiene | 8/10 | 657 agent-free tests, mypy strict over 71 files, ruff clean, deterministic tooling. |
| Docs truthfulness | **4/10** | The known failure mode recurred, in code shipped in the last 48 hours. |
| **Overall** | **~6/10** | |

## The one-line verdict

**AREA's design is ahead of its enforcement, and the gap widened in the last 48 hours** —
not because the method is wrong, but because the person writing the code graded it.
Three of the four worst findings (S1, S2, H1) are claims the repo makes about controls
that do not hold, and S3 ships a closed hole back open.

## Remaining order

1. ~~S3, S1, S2, S4~~ — done. ~~H1~~, ~~H2~~, ~~H3~~, ~~H4~~ (+ H4b) — done.
2. ~~H5~~, ~~H6~~ — done. Neither was the one-liner it looked like: H5's "stronger" fix would have installed a hook that always fails open, and H6's `esc()` does not escape quotes.
3. **H5, M1–M5** — a docs-truth pass, same shape as the one in PR #34.
4. The unverified list above — first-hand check before any is treated as real.

## The question this audit leaves behind

S1 was a *previously remediated* finding whose remediation moved the **decision** but not
the **measurement**. That is a repeatable mistake, not a one-off, so every other
"remediated" claim deserves the same question asked of it: after the fix, what actually
re-measures the thing being claimed — and is that measurement in the oracle the loop
converges on, or beside it?
