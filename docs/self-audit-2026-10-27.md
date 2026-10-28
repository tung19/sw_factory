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
> lives. Everything below is now closed except **M5**. Each fix section records what
> changed.

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

### M6 · 15 profiles declared `skills: none` but their agents can still read the pack — FIXED (Tung chose (b))

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

**Tung chose (b): record it.** The reasoning that settled it is that (b) errs toward
*"this changed, re-measure"* rather than *"nothing changed, trust the old baseline"*,
which is the posture everything else in this audit moved toward — and the cost is
currently **zero**, because no run carries a profile digest yet, so there is no baseline
to invalidate. Option (c), declaring per-kind which skills are relevant, was rejected:
nothing measures that, so it would be another unverified claim of exactly the kind this
audit spent the day deleting.

`skills:` now takes a third value, `inherited`, and `profile_digest` folds the skills
hash for `all` **and** `inherited`. Which kinds get it was **measured from the call
sites**, not guessed: the six that pass the APP directory to the engine (`auditor`,
`chaos-author`, `e2e-author`, `holdout-author`, `holdout-fixer`,
`holdout-readjudicator`). The `ask_cli` kinds (`product-reviewer`, `spec-reviewer`) run
in a temp dir and the spec/inception/research kinds run in a spec or scratch directory,
so they stay `none`. One honest caveat is recorded in the code: on a **first** `--tdd`
build the holdout author runs before `build_app` installs anything, so its inheritance is
conditional — it is marked `inherited` anyway, for the same err-toward-re-measuring
reason.

Measured effect: a skill edit now moves **7 of 16** profile digests, up from 1.

Two things this surfaced, both fixed here: an unknown `skills:` value used to be read
silently as `none` — which would quietly drop that kind out of the skills digest, the
exact failure the field exists to prevent — and making it raise initially broke
`load_profile`'s non-strict contract, where `evals.compare` branches on `prof is None`
and would have crashed instead of reporting the profile broken.

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

- **M1 · FIXED — `SECURITY.md:43` says "*every* agent/build/provider subprocess has a wall clock"** —
  four do not: `area/verify/nfr.py:106` (the full `--nfr-build`) and
  `area/build/cf_scaffold.py:100,109,296` (incl. `npm run build:cf`, the fallback build).
  The deploy CLIs genuinely are capped; the sentence overstates to "every".
- **M2 · FIXED — `tools/gate.sh` silently ignored `--chaos`** — `tools/gate.sh:11` parses only
  `--strict|--e2e`, and the script runs no chaos gate at all, while `CLAUDE.md` step 3
  instructs the builder to pass `--e2e --chaos`. The factory's master rule set names a
  flag its own tool drops.

  **Fixed, and the finding undercounted it.** M1 named two `npm ls` calls; sweeping for
  the whole class found **six** uncapped `subprocess.run` sites, including the two longest
  commands in the factory — `cf_scaffold._npm_run` (`npm run build:cf`, the CF fallback
  build) and `nfr.measure`'s `--nfr-build` full production build — plus `demo.sh` and
  `export._run`. Two `except OSError` clauses also had to learn about `TimeoutExpired`,
  which is a `SubprocessError` and would otherwise have escaped the helper that exists to
  degrade gracefully.

  The default used to live only in the adapter while four other modules had none — which
  is how the SECURITY.md claim drifted from the code — so it now lives once in
  `area/_util.cmd_timeout()` and the adapter delegates: one dial (`AREA_CMD_TIMEOUT`),
  read at call time, `0` to disable. Two sites are deliberately uncapped and allow-listed
  **with reasons**: the operator's `$EDITOR` (a clock would kill their session
  mid-sentence) and a dashboard job (it runs as long as the build takes and has an
  explicit stop button instead — `JobManager.cancel()`).

  `tests/test_every_build_command_has_a_clock.py` parses `area/` with `ast` and fails on
  any new uncapped call, on a `Popen` with neither a bounded wait nor a cancel path, on a
  second definition of the dial, and on an allow-list entry whose function no longer
  exists — a stale allow-list stops protecting anything while still looking like a
  decision. Verified to go red by removing the `nfr` cap, with an `assert` on the
  injection so the proof could not be hollow.

  **Fixed, and it was worse than a dropped flag.** The same script's e2e gate looked in
  `workspace/apps/$APP` — a repo-relative path — while generated apps live in
  AREA_WORKSPACE. So it never found them and printed *"chưa có e2e/ — hãy tự viết
  Playwright specs"*: **blaming the operator for missing specs while 12 of them sat in the
  real app directory.** `--e2e` is MANDATORY for any app with auth/sessions/forms
  (CLAUDE.md step 3), so the one gate the rules call non-optional was the one being
  skipped. The app directory is now resolved through `area.paths` (the visual gate in the
  same file already did it right), `--chaos` runs, `--perf` was added — it had never run
  here at all, though CASE-STUDY tabled a perf result — an unknown flag is now a **hard
  error** rather than a silent no-op, and the script states that it covers 5 of the
  registry's 9 gates. Proven live: `--e2e` 15 passed, `--chaos` 55 passed.

  **And the same bug was in two more scripts, both named by CLAUDE.md** — found by asking
  where else a repo-relative workspace default survived, after Tung asked whether the e2e
  message needed anything more:
  - `tools/lock-holdout.sh <name>` (step 1b, the CHECKSUM enforcement the whole method
    rests on) → *"không thấy holdout — hãy viết test holdout (từ spec) trước"*, while the
    locked oracle sat in the real app directory.
  - `tools/verify-holdout-intact.sh <name>` (step 2, "before and after each build
    attempt") → the same.
  - `tools/scaffold-app.sh <name>` (step 0) was worse still, because it **writes**: it
    scaffolded the project into the repo while every later `area` command read from
    AREA_WORKSPACE — a split brain where the spec docs and the app the engine builds live
    in different trees.

  **My first fix for this was itself broken, and CI is what caught it.** It asked
  `.venv/bin/python` for the workspace and fell back to the literal `workspace/` when
  that was missing — so in any checkout without a venv (CI, a fresh clone before
  `make install`) it silently reverted to the bug it was fixing. The local suite could
  not catch it, because the local checkout has a venv. `gate.sh` also exited **127**
  (`.venv/bin/python: No such file or directory`) where it meant "no such app". A second
  bug in the same fix: the default was `$PWD`-relative, while `lock-holdout.sh` and
  `verify-holdout-intact.sh` do not cd to the repo root, so it meant a different
  directory depending on where the operator stood.

  Resolution now lives in `tools/_workspace.sh`, shared by all four scripts so they
  cannot drift: **pure shell** (no interpreter, mirroring `area.paths.workspace()`),
  **anchored on the script's own location** rather than `$PWD`, with tilde expanded by
  hand rather than through `eval`. Verified under the exact CI condition — a copy of
  `tools/` with no `.venv` beside it, invoked from `/` — for both branches, with
  `AREA_WORKSPACE` set and unset.

  All three now resolve the workspace through that resolver. The Python callers always
  passed it explicitly, so the engine was never affected; it was the documented MANUAL
  path that was broken. `tests/test_tools_find_the_real_workspace.py` pins the round-trip,
  proves the lock still detects both an edited file and an ADDED one, and fails if the
  literal `${2:-workspace}` default ever comes back — that guard is what found the third
  script.
- **M3 · FIXED — the showcase "gate evidence" was a pre-fix artifact** —
  `examples/taskboard/SPEC/provenance.json` is `area.slsa-like/v1`, `builder:
  "area/openhands-acp"` (the hardcoded literal the changelog says was fixed), and
  `gates: {holdout_tdd: true}` — one gate, no `{ran,blocking,blocked}`, no `policy`.
  `docs/CASE-STUDY.md:72-79` tables audit/nfr/perf/e2e/chaos as ✅ and `README.md:24-26`
  calls the directory "the gate evidence".

  **Fixed by re-measuring, which found two more things wrong.** Every row of the
  CASE-STUDY table is now dated and carries the command that produces it. `nfr` was tabled
  "✅ within budget" and is **over** it (bundle 16403 KiB / 5120; advisory only because no
  `nfr.yaml` is committed). And `perf` could not be reproduced **at all**: `_pick_start_cmd`
  treated the existence of `.next` as "a build exists", so it chose the production `start`
  script for a tree whose `.next` came from `next dev`; `next start` exited with "Could not
  find a production build", which the gate reported as "booted but never became ready" and
  **skipped** — advisory, so green. It now requires `.next/BUILD_ID` and **quotes the
  server's own error** instead of swallowing it (`visual` boots through the same helper and
  got the same treatment). With a real build the original numbers reproduce almost exactly
  (p50 18.5 ms, 513 req/s vs the tabled ~19 ms / ~505), so they were honest — just
  unverifiable from the committed state. The committed `provenance.json` is now described
  for what it is (v1, one gate, 2026-10-20) and deliberately **not** regenerated by hand:
  an attestation that did not come out of the gated build path is worth less than an honest
  older one. Also confirmed from the audit's SUSPECTED list: `npm test` prints **73**
  (18 holdout + 55 chaos), never 18, because `vitest.config.mts` includes all of
  `__tests__/**`.
- **M4 · FIXED — stale counts** — `569 tests` in `CONTRIBUTING.md:26` and `docs/UPGRADE-PLAN.md:12`
  vs **657**; `docs/ARCHITECTURE.md:52` "the 9 gates below" over an 8-row table (`visual`
  has no row); `UPGRADE-PLAN.md:47` "8 gates"; `PLAN.md:101,201` "59/56 modules" vs 71.

  **Fixed at the source rather than refreshed.** A count nobody re-measures goes stale
  again next week, so the precise figures are simply gone from the living docs (`make test`
  prints the real one); only CHANGELOG entries keep numbers, where they are a historical
  record. The missing `visual` row was added, and
  `tests/test_gate_registry.py` now fails if any gate in `_GATE_ORDER` has no row in that
  table — verified to fail by removing the row and watching it go red, so it is not a test
  that passes vacuously.
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

### M7 · the cost gate printed a partial total as the total — FIXED

Found by Tung asking what the "$176.84" in the ledger actually is. Answering it properly
meant reading `obs.cost_of()` and the gate, and the answer has three parts, only the
first of which was already written down:

1. **It is not a bill.** `obs.cost_of()` reads `accumulated_cost` from the OpenHands
   SDK, which prices the tokens an agent used at the model's list price. All $176.84 came
   from `backend=ACPAgent` — the **keyless** path through the Claude Code login — between
   2026-10-18 and 2026-10-21. On a Claude subscription that usage counts against plan
   limits, not a per-token invoice. The `--backend llm` path (`LLM_API_KEY`) is where the
   same number *is* real per-token billing.
2. **The ledger is partial** — *and this is the part I got wrong; see M8.* What I
   reported was "110 of 204 rows carry a cost; `_Agent` (68) and `claude-cli` (26)
   report none". Those 94 unpriced rows were **written by AREA's own test suite**, which
   had been appending to the real ledger. On the 110 genuine runs, coverage is
   **110/110** and the $176.84 covers all of them. The *claim* survives on source rather
   than telemetry: `ask_cli` logs `cost=None` unconditionally
   (`area/engine/adapter.py:196`) and is what runs the independent spec reviewer, the
   product gate and web intake — so a build that reviews its spec does have rows the
   gate cannot price. But I reached a true conclusion from contaminated evidence, which
   is luck, not method.
3. **And the gate did not say so.** `build_cost()` drops unpriced rows and sums the rest.
   The all-unpriced case was already handled loudly (an earlier remediation), but the
   PARTIAL case took the normal path: three priced runs out of eight printed
   `$0.42 spent / $5.00 cap — ok`, which reads as "this build cost $0.42".

`cost_coverage()` now reports (priced, total) in scope; the gate prints it whenever
anything is unpriced, states that the real total is **≥** the measured one rather than
**=** it, and never prints a bare `ok` over partial data — `UNVERIFIED` by default,
`FAIL` under `--strict`. Not blocking by default on purpose: `ask_cli` stages are
unpriced, so blocking would fail almost every build that runs a spec review, which is a
false block rather than a finding. A measured breach still blocks regardless of coverage,
since partial pricing can only *understate* spend.

### M8 · AREA's test suite was writing to the user's real telemetry ledger — FIXED

Found while answering M7: the ledger had 218 rows, and the ones carrying no cost looked
structural. They were not. `obs.log_run` appends to `WORKSPACE/.area/runs.jsonl` — the
real one — inside `except Exception: pass`, so a test that drives the genuine `run_until`
or `ask_cli` pollutes production telemetry **and still passes**.
`tests/test_scrub_covers_the_build.py`, written the same afternoon, did exactly that:
three records per suite run, **108 accumulated**. Because `obs._current_app` is a
process-global that no test resets, they inherited the app name of whichever test had
last called `set_app`, so they read as real agent runs on a real app.

The damage was not hypothetical. That ledger is what `area cost` prices and what
`area evals` uses as its A/B baseline, and the fakes had already produced one wrong
answer *inside this document* (M7 point 2) and one to Tung directly.

`tests/conftest.py` now carries an autouse fixture pointing `obs.RUNS` at `tmp_path` and
resetting `_current_app`, so it covers tests not yet written.
`tests/test_the_suite_never_writes_the_real_ledger.py` asserts it by **observing the real
file**, not by inspecting the fixture — with the fixture disabled, 3 of its 4 tests go red
and the real ledger grows by 2 in that run. The 108 synthetic rows were removed, keyed on
a synthetic backend **and** the test window so a genuine `ask_cli` run could not be caught
by it; the original is kept at `runs.jsonl.bak-2026-10-28`.

### M9 · `area evals` is priced out of ever returning a verdict — option 1b DONE (2026-10-28)

Found by trying to run the A/B Tung asked for. The mechanism is sound; the **version
granularity** makes it unaffordable, and the two facts together mean the gate can
essentially never be decisive.

Measured, not reasoned:

- Between `543c1448` (pre-#40) and `HEAD`, the **only** hashed input that changed is
  `skills/vinext-cf-build/SKILL.md`. `area/build/nextjs.py` and `profiles/builder.yaml`
  are untouched.
- That one edit re-versioned **7 of 16 kinds**: `auditor`, `builder`, `chaos-author`,
  `e2e-author`, `holdout-author`, `holdout-fixer`, `holdout-readjudicator`. That set is
  **identical** to the set declaring `skills: all` or `inherited` — so a *Cloudflare*
  skill moved the versions of the e2e author, the chaos author and the auditor.
- A new version has no baseline, and `MIN_RUNS = 5` is per side **per kind**. The three
  declared tasks give 3 runs per kind per pass, so a verdict needs 2 repeats: **12
  builds**. From the cleaned ledger, a build-session is median **$5.94** / 15 min, mean
  $9.82, max $37.23 — so **~$71 of token value and ~3h serially, after any skill edit.**
- And the change in that window is invisible to the task set anyway: all three declared
  tasks are `--target plain`, where a Cloudflare skill does nothing. Nor can the set be
  extended to see it — **no Cloudflare app has a locked holdout**, and the eval set
  requires one.

The coarseness is deliberate; `area/profile.py:96-107` argues for erring toward "this
changed, re-measure". The flaw is not the conservatism, it is that nothing weighed the
**price** of re-measuring, so the honest posture and the affordable posture never met.

Not fixed here, on purpose. The digest *is* the oracle for a factory change, and
"is the oracle itself correct?" is a spec question — CLAUDE.md puts that with Tung, not
with the thing being graded. The options, cheapest first:

1. **Scope the skills term to the skills a kind can actually use** (per-skill hashes
   rather than one pack digest), so a CF skill edit re-versions only the kinds a CF
   build uses. Keeps the conservatism where it is load-bearing.

   **Tung chose this one; shipped 2026-10-28.** Two halves, and the first is what makes
   the second honest. (a) A skill declares its scope in its own SKILL.md frontmatter
   (`targets: [cloudflare]`), and `install_skills` is target-aware — so a plain app never
   *receives* the CF skill. Previously `skills_preamble` declined to NAME it for a plain
   build while the installer copied it in regardless, so a Claude Code session in that
   directory could still discover it. (b) `profile_digest`'s skills term is split by
   scope: universal skills version every kind that runs where the pack is (`all` and
   `inherited`), domain skills version only the kinds that INSTALL them (`all`).
   `provenance.skills_digest()` deliberately still covers the WHOLE pack — a version
   answers "what can change this kind", an attestation answers "what shaped this build",
   and narrowing the second would make provenance claim less than the truth.

   **Measured, same experiment as above:** editing one Cloudflare skill now re-versions
   **1 of 16** kinds (`builder`) instead of 7, while editing the universal
   `area-oracle-loop` still re-versions all 7. 824 tests.

   **Residual — CLOSED 2026-10-28.** An `inherited` kind's behaviour change specific to
   a domain target was not separately versioned: the digest comes from the PROFILE, so
   the same kind in a Cloudflare app and in a plain app carried the same version while
   seeing different packs. Measured on this machine, which is what made it concrete:
   `apps/taskboard/.claude/skills/` holds `area-oracle-loop` + `vinext-cf-build` (built
   before target scoping) while `apps/expenses/` holds `area-oracle-loop` alone — two
   packs, indistinguishable in the ledger.

   `obs.installed_skills()` now reads `<app>/.claude/skills/` and stamps
   `(skills_digest, skills)` on every run, and `compare` returns a new
   **`confounded-skills`** verdict when the two sides ran with different packs: ranked
   with `unpaired` because more runs cannot separate a difference in KNOWLEDGE from the
   change under test, and **not** strict-only, because that is a comparison which cannot
   be made rather than one with too little data. Absence of a digest (legacy runs, and
   every `spec` run, which happens before the app exists) must not read as disagreement,
   or every old ledger would become permanently unusable — there is a test for that.

   Done now rather than later because `evals` is what F4 would be graded by: comparing
   across packs would have spent F4's ~$40–50 of builds on a measurement that attributes
   a change in domain knowledge to the thing under test.
2. **Let `MIN_RUNS` fall for a matched-pairs design** — defensible statistically, since
   pairing removes the between-task variance the threshold is guarding against, but it
   is also the option that fits the measurement to the budget, so it needs saying out
   loud rather than quietly.
3. **Leave it, and accept that `evals` is a tripwire for "something changed", not a
   grader.** It would then be honest to say so in its own output.

### M10 · the `--clarify` gate implemented the STOP without the RESUME — FIXED (2026-10-28)

Found by trying to run a real build, three times, and never getting one. The gate
prints *"Confirm/override then re-run"*. Nothing an operator can do satisfies it:

| the offered exit | what it actually does |
|---|---|
| `--expect "<examples>"` | text appended to the **extraction** prompt (`extract.expected_block`); never reaches `_clarify_gate` |
| edit `material: false` | **destroyed** — the extractor rewrites `assumptions.yaml` every run |
| a confirm verb | **did not exist** — 32 handlers, no `clarify`/`confirm` |
| `--no-clarify` | removes the gate rather than answering it |

So the real choice was **"cannot build" or "no gate"**, with nothing between — and each
attempt cost a fresh spec extraction plus an unpriced `ask_cli` review (~$0.50 + an
unmeasurable half, ~2 min).

**It also does not converge.** Measured on one app over three runs: **8 → 2 → 11**
material assumptions. Answering a question in the requirement makes the independent
reviewer ask the *next* question down — attempt 2 asked "how does the user type an
amount", attempt 3 answered that and was asked "which strings count as valid: leading
`+`, bare `.50`, comma decimal marks, thousands separators?". `material` is also the
agent's **own** label (`extract.py:52` tells it to record its guesses), uncalibrated and
uncapped, which is why the count swings. So "every question answered" is not a reachable
state, and a gate keyed to it can only ever say no.

Three of attempt 3's eleven were worth the stop, which is why the answer is not to
weaken it: nothing enforced "local-only" (`next dev` binds every interface);
`AC-14` asserts "no outbound network requests" while Next telemetry and `next/font`
make several by default, so **that acceptance criterion would have passed by accident**;
and `./data/expenses.db` was headed for version control with real spending data in it.

**The fix is a resume, not a loosening.** CLAUDE.md puts the human as the top gate; an
unanswerable stop is not a gate, it is a wall. New `area/spec/clarify.py` +
`area clarify <name> [--confirm-all] [--answer N="…"]` records the decision in
`specs/<name>/clarified.yaml`, **anchored on the spec digest** rather than on question
text — because per-question closure is unreachable, while "the human reviewed THIS
spec" is reachable and bounded: change the requirement and it expires. `clarified.yaml`
is deliberately **not** in `provenance._MATERIALS`, so recording a confirmation cannot
expire itself.

`extract_spec(reuse=True)` / `area run --use-spec` is the other half, and without it the
first half is useless: the extractor is an LLM, so re-running it yields a different spec
with a different digest, expiring the confirmation just given — and would mean the spec
reviewed is not the spec built. It also makes confirming free.

`--confirm-all` deliberately does **not** feed the agent's own assumptions back to the
extractor as answers; repeating a guess would dress it up as a decision. Only answers a
human types become authoritative input.

12 tests, one shown to go red against the old gate. Dogfooded on the real `expenses`
spec: 11 open → confirmed → silent → spec edited → 11 open again → spec restored →
silent. The confirmation written during that dogfood was then **deleted**, because
leaving a record claiming a human reviewed 11 assumptions they had not seen is the same
category of error as a hand-written attestation.

### M11 · AREA enforced the oracle's INDEPENDENCE and never measured its STRENGTH — FIXED (2026-10-28)

Found by building a real app and then **re-running its locked oracle**, which the build
had just reported green.

The spine is *"quality ≤ strength + **independence** of the oracle"*. Independence is
enforced hard — a separate agent authors the suite from the spec alone, it is
checksum-frozen, and the build oracle refuses if a locked file was modified or did not
execute. **Strength was never measured at all**, and `_authoring_oracle`'s coverage
check is "the AC id appears in the test text", which cannot tell an assertion from a
`grep`.

What that permitted, in `expenses` AC-14 — *"the app makes no outbound network
requests"*, a property of the **running** system, "verified" by grepping source for
HTTP client names:

- **false negative:** PASS while `next telemetry status` reported `Status: Enabled`;
- **false positive:** on re-run it **FAILED** on a documentation URL inside a comment in
  the generated `next-env.d.ts`.

Maximally independent, nearly powerless, and nothing anywhere said so. The independent
spec reviewer had predicted it almost verbatim (*"AC-14 passes only by accident or fails
on a technicality nobody scoped"*) — and that finding was printed as one of eleven
`material` assumptions and then discarded, which is the second half of the defect:
**a measurement that cannot measure was routed to the human as a product decision.**
Confirming "append-only has no correction path" is meaningful; confirming "AC-14 passes
by accident" is not — no human answer makes an invalid oracle valid.

The fix follows IEEE 1233 (verifiability is an attribute of the requirement, proven by
**execution / inspection / demonstration / analysis**) and the established practice of
reporting an **"unable to verify"** result *separately from the pass rate*:

1. **`verify_by` on `AcceptanceCriterion`** — the spec stage must state how a `then` is
   to be proven. `Optional`, so the four existing apps still load; an unstated method is
   reported as **unstated**, which is the truth, rather than defaulted to one nobody
   chose.
2. **`area/verify/strength.py`** — pure and deterministic, like the rest of the authoring
   oracle. For a criterion declaring `execution`, the enclosing `describe`/`it` block
   must drive the app through its public surface (`../../lib/…`) rather than only read
   it. Scoped per criterion by brace matching, so one file that drives the app somewhere
   cannot launder a grep-only criterion inside it; an unresolvable structure guesses
   toward "fine", because a false block on an honest suite costs more than a missed weak
   one.
3. **Blocking only under `--strict`, and from INSIDE `_authoring_oracle`** — so the
   decision is a term in the verifier the authoring loop converges on, not a note beside
   it ([[area-fix-moves-decision-not-measurement]]). Advisory by default: an
   approximating oracle is a legitimate choice as long as it is labelled, and failing
   every app with one hard-to-observe criterion would be a false block.
4. **`provenance.oracle`** — `{criteria, unableToVerify, methodUnstated}`, so a reader
   can tell a strong green from a decorative one. Reported, never blocking.

Measured on the real app: with AC-14 declared `execution`, the check reports
`1 UNABLE TO VERIFY (AC-14: declared execution but the test only reads the source)`.
As committed, `expenses` records all 14 criteria as `methodUnstated` — it predates the
field, and that is stated rather than papered over.

16 tests, 4 shown to go red when reverted.

### M12 · the preview step mutates the app AFTER provenance attests it — FIXED (2026-10-28)

Same build, same minute. `provenance.json` was written at **09:13:39**; AREA then ran
`npm run dev` to open a preview, which regenerated `next-env.d.ts` at **09:13:40**. The
attested `artifactDigest` is `75f7cd5e…`; the app on disk now digests to `af97d656…`.

So the attestation describes an app that no longer exists, and `area deploy` would refuse
it — fail-closed working correctly, protecting the operator from an app **the factory
itself broke one second after certifying it**. It is also what made AC-14 flip from pass
to fail on re-run, which is how M11 was found at all.

This is the class #34 already fixed once (`harden_cf_app` mutated the app after
`verify_provenance`), recurring through a path nobody considered: the **post-build
preview**.

**Fixed as a rule, not as a patch about the preview: an attestation describes an
ARTIFACT, not a moment.** `#34`'s answer was "mutate before the gates, and keep a
tripwire that refuses if anything changed" (`deploy._settle_before_attesting`). That is
right for `harden_cf_app`, whose bytes SHIP — but wrong here, because it would refuse
every app whose preview was ever opened. The preview's writes are toolchain-generated or
runtime state and ship nowhere, so they are out of the digest:
`_SKIP_FILES` + `_SKIP_SUFFIXES` exclude `next-env.d.ts`, `*.tsbuildinfo`,
`.eslintcache`, `*.log` and the SQLite family (`*.db`, `-wal`, `-shm`, `*.sqlite*`).
Every authored file is still digested, including a hand-written `types.d.ts` — only
`next-env.d.ts` is excluded by name, so "any `.d.ts`" never becomes a blind spot.

The wider case this closes was not in the original finding and is worse: **`expenses`
persists to `./data/expenses.db`, so a human clicking through the preview AREA itself
opens and saving one row would have made the build undeployable.** Every app that stores
data had that.

**And fixing it exposed a defect in the fix.** Widening the exclusions changes what the
digest asks, so every attestation recorded under the old rules stopped comparing — and
`verify_provenance` reported that as *"artifact digest CHANGED since it was gated"*,
i.e. accused the operator of drift for an upgrade AREA performed. Measured honestly: of
the four attested apps, three had already drifted for their own reasons and **only
`fb_incept` was validly attested and invalidated by this change** — but the wrong-reason
bug would recur on every future edit of the list. So the algorithm is versioned
(`DIGEST_VERSION`, recorded as `product.digestVersion`), and a version mismatch returns
a distinct **`stale-digest`** status that still fails closed while saying what actually
happened. `deploy_with_gate` gets an explicit branch for it rather than inheriting the
`absent` one, because leaning on `else` for a status nobody anticipated is how fail-open
creeps back. A v1 record whose number still MATCHES is reported `ok` — the bytes are
provably unchanged whatever the definition, and refusing would be a false alarm. That
last case was found by a test of mine failing.

`expenses` itself is NOT repaired by this: its AC-14 test greps the app's own files, and
`next-env.d.ts` is still on disk. That criterion is a genuinely invalid locked oracle, so
per CLAUDE.md it is not edited — `__tests__/_holdout/_CHALLENGE.md` states the case in
both directions and **awaits Tung**. Writing it does not disturb the lock
(`verify-holdout-intact.sh`: intact), which is the first real use of that escape hatch.

### M13 · the oracle required files that register no tests to have "run" — FIXED (2026-10-28)

`assert_locked_files_ran` (the S4 fix) required **every** locked `.ts` file to appear in
the runner's report. Holdout authors legitimately lock shared helpers — `expenses` has
`_source-scan.ts` — and a runner that collects one reports "no test suite found in
file": a failure for having obeyed the lock. Satisfying it cost a real build **an entire
extra attempt**, which is real money, and every `--tdd` build paid it.

Now only locked files that **register** a test (`it(`/`test(`/`describe(`) must have
executed. This does not weaken the guard S4 exists for: the attack is a builder
excluding or shadowing locked test files so a green exit code hides an oracle that never
ran, and a file's registrations are part of its checksum-locked bytes — tests cannot be
hidden in an `_`-prefixed module to escape the requirement, and there is a test for that.
An unreadable file still counts as "has tests", the safe direction. A lock containing
only helpers now says "no runnable locked test files to confirm" instead of implying a
suite executed.

**How it was found is the point: this is the first lesson the experience store ever
harvested** (F1b, shipped hours earlier). The builder wrote it while fixing the build,
AREA stored it, and reading it surfaced a defect in AREA itself — the memory mechanism
working as designed rather than merely passing its tests.



### M14 · five lists said what "not app source" means, and they disagreed — FIXED (2026-10-28)

Found by auditing the seams where the day's work meets **Flow B**, the flow none of it
had been run against. Not by another incident — which is the point: M12 cost a build to
discover, and this is the same class found for nothing.

`area/provenance.py`, `area/verify/visual.py`, `area/re/ui_capture.py`,
`area/screen.py` and `area/web/jobs.py` each carried their own set of "junk" paths.
`artifact_digest` **hashed four directories the others already excluded**, so an
attestation could be invalidated by work that changes no source at all:

| digested, but generated | the operator action that broke the attestation |
|---|---|
| `.visual/` | **re-running `area visual <name>` to look at a score** |
| `coverage/` | **running the test suite** |
| `out/` | a Next.js static export (`output: 'export'`) — **every build** |
| `.turbo/` | any turbo-cached command |

`.visual/` is the sharpest: the visual gate is **auto-selected** for a clone with
captured UI (#35), so on the Flow B path a human who looked twice at their own parity
score would have been told the artifact had changed since gating.

One canonical set now lives in `area/paths.py` (`GENERATED_DIRS`, plus
`GENERATED_AT_ROOT` for `dist`/`build`, which are junk only at the app root because
`src/build/helpers.ts` is real code). All five modules derive from it. The one
purpose-specific exception is kept and explained: `visual` and `ui_capture` also skip
`.area-ui`, because that is the vendored **reference** UI and scanning it as the clone's
own markup would compare the reference against itself — a statement about those gates'
job, not about what app source is.

11 tests; 8 go red when provenance is given its own list back. The one that matters is
the last: it fails if **any** module ever again treats something as generated that the
attestation still digests, and a second asserts they are not merely in agreement today
but derived from the same set.

### M15 · a local-path clone silently lost the entire UI half of Flow B — FIXED (2026-10-28)

Found while choosing a reference for the first real `area clone` run, which is the
cheapest a finding has been: **$0, and it would have cost ~$10 to NOT discover.**

`capture_ui_evidence` captures from `_sample/`, or from a live http(s) source. The RE
prompt said *"local path -> read the files there"*, so nothing ever created `_sample/`
for a path. Measured per kind:

    kind=path  captured=False   "no _sample/ tree and source is not an http(s) URL"
    kind=url   captured=True

With no UI evidence, `_with_ui_parity` has nothing to bolt onto the build oracle and the
visual gate is never auto-selected. So **`area clone ./some-app --tdd` — the most
natural invocation there is — produced a GREEN build with the whole UI-parity half of
Flow B inert.** That is #35's entire contribution ("the UI is now a TERM IN THE BUILD
ORACLE") disabled by the choice of reference kind, while reporting success. Had the run
happened first, the report would have been "clone green" and the omission invisible.

The intent was always otherwise — `capture_ui_evidence`'s own docstring says "`_sample/`
tree (repo/**local-path** reference cloned by RE)". So this is an implementation gap
against stated intent, not a design disagreement. `isolate_local_path` copies the
reference into `_sample/` before the RE agent runs, skipping `GENERATED_DIRS`, and the
prompt now points the agent there with the do-not-run rule attached — which also
enforces `.claude/skills/clone-from-source`'s requirement that the reference be
ISOLATED and READ rather than read in place. Idempotent: an existing `_sample/` is left
alone, so a re-run cannot swap the evidence an earlier spec was derived from.

Measured on the real reference: **1.4 GB → 53 files, 0.3 MB, 0.5 s**, with
`node_modules`/`.next` skipped and `app/` intact — and `capture_ui_evidence` then
returns `captured=True` with 5 rendered files, 1 stylesheet and 3 design tokens. The
affordability is a direct consequence of M14's single `GENERATED_DIRS` set.

11 tests. The first ten passed **with the call site removed**, because they exercised
`isolate_local_path` directly — the same wiring blind spot F3 had. The eleventh drives
the real `spec_from_source` with only the agent stubbed, asserts `_sample/` exists *when
the agent is invoked*, and goes red without the call.

### M16 · the spec had nowhere to record a route map, so clone parity was undetermined — FIXED (2026-10-28)

Found by running Flow B for real — the first time it has been run on this code. It cost
**$1.76** (one `re` run; the `spec-review` beside it was unpriced, per M7) and it is the
finding reading could not reach: `Spec`'s field list was read twice today without the
absence meaning anything, until the clone's own reviewer pointed at the consequence.

The reverse-engineer stage read `taskboard` *well*. It recovered `node:sqlite` with
`TASKBOARD_DB`, the `scrypt$<saltHex>$<hashHex>` format with a 16-byte salt, and the
stateless HMAC-SHA256 `sid` cookie with its 7-day max-age. And it recorded **no routes**,
because `Spec` was `name, summary, stack, entities, features, ui` — there was nowhere to
put them. Its independent reviewer caught it:

> *"What are the actual URLs? No document states the path of the login page, the
> boards-list page, or a board-detail page — yet AC-8 and AC-22 require requesting a
> board URL directly."* → assumption on file: **"Invent a plausible map."**

Measured: the real routes (`/`, `/login`, `/boards`, `/boards/[id]`) were readable from
`_sample/app/` in a second, and the generated `acceptance.yaml` quoted **zero** paths —
**15 of its 24 criteria navigate somewhere without naming where.**

**Why this is an oracle defect, not a documentation gap.** `author_until` is handed
`acc_yaml` **alone** and never sees `spec.yaml`. A path absent from the criteria is a path
the holdout author invents — and then the suite is checksum-frozen, the clone is built to
satisfy it, `verify-holdout-intact.sh` reports the oracle intact, and the whole apparatus
asserts parity against a URL neither app serves. Independent, frozen, and measuring
something that does not exist: M11's class, reached by a different road.

Same shape as the missing `ui` field that #27/#28 added after "the clone's UI is wrong" —
RE was capturing features and the data model, and everything else had no home.

The fix has two halves, because one would not work:

1. **`Route` + `Spec.routes`** — the structured record of what the app serves. Optional,
   so the four existing apps still load.
2. **The criteria must quote the literal path**, since that is the only thing the holdout
   author reads. Both the shared `_SCHEMA_GUIDE` and the RE prompt now say so, and the RE
   prompt adds that for a clone this is *discovery, not invention* — a Next.js app's paths
   are visible in its `app/` tree.

`validate_cross` enforces the fatal case: a spec whose criteria navigate while declaring
**no** routes is rejected, so the spec stage iterates instead of handing the oracle a
guess. A single prose-only criterion is reported by `routes_unquoted` but not fatal —
blocking each one would be a false block, as a sibling criterion often pins the path.

15 tests, including the navigation verbs (a missed phrasing brings the hole straight
back) and the four real routes as a fixture, so the test is the measurement rather than an
invention. Run against the live clone spec, the new verdict fires exactly as described.

### M17 · the clarify gate's resume existed on one flow in three — FIXED (2026-10-28)

Found immediately after M16, by asking how I would actually re-run the clone: **M10 gave
the gate a resume, and gave it only to `area run`.**

A clone that stops at the clarify gate could record a confirmation
(`area clarify <name> --confirm-all`) and then had **no way to build it**:

* `area clone` re-investigates the reference, producing a different spec with a
  different digest — **expiring the confirmation it had just been given**;
* `area run --use-spec` has no `reference` parameter, so it cannot build in parity mode
  at all — the clone would come out as a fresh app that happens to share a spec.

So for Flow B and intake, the gate was still the wall M10 was written to remove. This is
the identical shape to `--strict` being inert on two flows (#54), **found the same way
and two hours later** — which says the real lesson is about how a capability gets added
here, not about either flag: a feature threaded through `run_pipeline` looks done, passes
its tests, and is absent from two thirds of the product.

`spec_from_source` and `spec_from_aidlc` now take `reuse`, mirroring `extract_spec`;
`clone_pipeline` and `intake_pipeline` take `use_spec` and pass it; both commands expose
`--use-spec`. For a clone, `_sample/` is left in place by the idempotent isolation
(M15), so a reused spec still has the evidence the build needs for parity.

The guard lives beside #54's, and is deliberately the same shape: for **every** pipeline
whose command offers the flag, assert the parameter exists; and for every command,
assert the flag is typeable. A flag the operator cannot type is not a resume, and a
parameter no command passes is not a feature.

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
3. ~~M1~~, ~~M2~~, ~~M3~~, ~~M4~~, ~~M6~~ — done. **M5** (the branch-scoped `area
   runner` entry point) remains.
4. ~~Harness² step (3)~~ — done: the experience log is evidence-gated
   (`area evals <kind> --record`, `--notes`). Fixing it first required scoping the
   profile digest to the behavioural fields, because hashing the prose meant writing a
   lesson down invalidated the measurements it described.
5. The unverified list above — first-hand check before any is treated as real. It is
   shorter than it was: `ask_cli` and the decoy-holdout item were both promoted to
   confirmed, fixed, and struck from it.

## The question this audit leaves behind

S1 was a *previously remediated* finding whose remediation moved the **decision** but not
the **measurement**. That is a repeatable mistake, not a one-off, so every other
"remediated" claim deserves the same question asked of it: after the fix, what actually
re-measures the thing being claimed — and is that measurement in the oracle the loop
converges on, or beside it?

S1, S4, H4 and H1 were all that same shape: the *claim* existed, the *measurement* did
not. So was M2 — a gate script that printed a reassuring warning instead of running the
gate.

**And it applies to the fixes in this document, not only to the code they fix.** Four of
them were only confirmed by an end-to-end run, not by reading: the audit gate's false
green needed the real control flow traced, the decoy holdout needed a real app with real
vitest, `screen.py` needed a real 517 KB minified bundle, and `perf`'s unreproducible
numbers needed the server actually started. Reading found none of those.

Worse, three fixes written *here* were themselves defective, and each was caught by a
measurement rather than a review:

- the first S4 fix resolved the lock keys against the app root instead of the holdout
  directory — it blocked the attack **and** every honest build, while printing a
  plausible reason. Only the honest-green case caught it.
- `evals.check()` imposed the repo's declared task set on any caller with its own root,
  so every verdict came back `unpaired`. An existing test caught it.
- the M2 workspace fix asked `.venv/bin/python` for the answer and fell back to the
  literal `workspace/` — so wherever there was no venv it **silently reverted to the bug
  it was fixing**. 705 local tests passed; **CI** caught it, because the local checkout
  has a venv and CI does not.

So the rule this audit actually leaves behind is narrower and more useful than "test
end-to-end":

> **Every guard must be proven to go red, and the proof must assert that it changed the
> thing it meant to change.**

Twice in one afternoon a "proof" here was hollow: a `str.replace` with the wrong
indentation silently did nothing, and a worktree built to simulate "no venv" held the
*committed* scripts and still reached the real venv. A `$?` read after a pipe did the
same thing earlier. Each produced a green result that looked like evidence and was not —
which is precisely the defect class above, turned on the person fixing it.
