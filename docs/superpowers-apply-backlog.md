# superpowers → AREA: internals pass, balanced pros/cons, and an apply backlog

Third pass, building on [compare-superpowers.md](compare-superpowers.md) and
[deep-eval-superpowers.md](deep-eval-superpowers.md). Those read the SKILL.md surface; this one
read the **internals** — ~7700 lines across ~70 `references/`, `scripts/`, prompt-template and
test files in `obra/superpowers` v7.0.1 — and weighs **both sides'** strengths and weaknesses so
we can decide what to actually apply to AREA.

---

## superpowers — ưu điểm worth borrowing (from the internals)

- **A scenario-based pressure-test method for discipline text:** RED baseline (run the scenario
  *without* the rule, capture the agent's excuses **verbatim**), write only enough to kill those
  excuses, then a REFACTOR loop (excuse|reality table + red-flags list) until "no new
  rationalization". Multi-pressure **forced-choice (A/B/C)** scenarios with "no easy outs".
- **A crafted blind-reviewer contract** (`task-reviewer-prompt.md`, `code-reviewer.md`): "treat the
  implementer's report as **unverified claims**"; "a stated rationale (e.g. YAGNI) **never downgrades
  severity**"; "spec silence is not permission; a reasonable person's expectation is a requirement";
  a **"Declined to judge"** channel so nothing is dropped silently; every finding needs `file:line`.
- **A compaction-proof progress ledger** (`task-done`/`task-start`/`resuming.md`): a script appends
  `Task N: complete` **only on a green test exit**; a run resumes by skipping completed tasks.
- **Separation-of-duties, stated as rules:** the implementer "may not spawn a reviewer / its approval
  counts for nothing"; the controller "never fixes findings itself" and does "no early adjudication
  before the cap"; a bounded **escalation ladder** (resume → fresh on a stronger model → ruling).
- **Citation-grounded post-mortems** (`diagnosing-superpowers`): independent per-dimension analysts,
  each finding `evidence: path:line — "quote"`, **ungrounded findings discarded mechanically**,
  analysts forbidden from proposing fixes. A **claim-vs-tool-result** check (every "done/passing"
  claim must have a tool result in the same turn).
- **Debugging techniques:** root-cause-tracing (instrument *before* the dangerous op), a
  **defense-in-depth environment guard** (e.g. "refuse git-init outside temp during tests"),
  condition-based `waitFor` instead of fixed sleeps.
- **A spec-completeness "builder-check":** a fresh subagent reads the design as an uninformed builder
  and returns only the **ranked questions a wrong guess would get wrong**, or "nothing important left".

## superpowers — nhược điểm (do NOT copy)

1. **Its guarantees are prompt-level, not mechanical.** "Independence" = fresh-context subagents of
   the **same model**; there is no checksum lock, no held-out oracle, no gate that blocks on failure.
   Reviewer independence, "no self-spawned reviewer", "controller doesn't fix" are all asked, not
   enforced. The only determinism is a few shell helpers.
2. **Its own method is same-reasoner-writes-and-grades.** The author-model reads the agent's
   rationalizations, writes the counter, and reruns the **same synthetic scenarios** — n=1, no reps,
   no variance, no held-out scenarios, no cost accounting; "Bulletproof achieved" after ~3 passes.
   This is exactly the failure AREA's locked holdout exists to prevent.
3. **Multi-harness maintenance burden:** 7 tool-mapping files (claude-code/codex/gemini/hermes/
   muse/pi/antigravity) hand-kept in sync; a tool rename upstream silently rots a mapping; parity is
   never verified (the "new harness" acceptance test is a single transcript).
4. **Packaging sprawl + brittle bash:** 3 loader conventions in `package.json` + a stub `index.js`;
   `find-polluter.sh` word-splits filenames and hard-codes `npm test`; a whole HTTP "visual companion"
   server with per-harness launch quirks.
5. **Token cost + unbounded text growth:** fresh subagents per task/review/fix-round (the files admit
   a final-review fix wave "cost more than all its tasks combined"); every closed loophole adds text
   to a skill loaded every run; prohibition-style bulletproofing **backfires** on format/omission
   failures, and the only stopping rule is "no new rationalization".
6. **Evidence is anecdotal** ("1847 tests passed", "60% → 100%", all one 2025-10-03 session); quality
   is held up by social rules (94% PR rejection, evals kept in a separate repo), not checkable here.

## sw_factory — ưu điểm (confirmed by the deep read)

- The **checksum-locked holdout authored before the code** has **no superpowers equivalent** — their
  reviewer reads the implementer's report, and the grading tests come from the same plan the
  implementer read. AREA's oracle is strictly more independent.
- Deterministic gates + **provenance** (spec→gates→artifact sha); `screen.py` is a **deterministic**
  secret filter (stronger than superpowers' LLM scrubber — use their *taxonomy* only).
- AREA's own `wording_probe` (5+ reps · no-guidance control · `inconclusive` verdict) **already beats
  superpowers' evidence standard** for grading process text.
- Single-harness: none of weaknesses #3/#4 above.

## sw_factory — nhược điểm (gaps the internals exposed)

- No compaction-proof **task-resume ledger** (only whole-build provenance) → `stale-oracle-mid-loop`.
- The orchestrating session **can still patch code itself**; no explicit "no self-spawned reviewer",
  no "no early adjudication", no escalation ladder.
- Self-audits are **prose**, not citation-grounded; no claim-vs-tool-result check → the
  `fix-moves-the-decision-not-the-measurement` bug class has no automated catcher.
- No spec-contradiction / ambiguity probe **before** locking the oracle.
- No **skill-description lint** — and `authoring-area-skills`'s own description summarizes its workflow
  ("Pressure-test … BEFORE … and never let the same reasoning write and grade"), which superpowers'
  `discovery.md` shows makes agents follow the summary instead of the skill. **Self-caught defect.**
- `wording_probe` is **not mutation-checked** — feed it a wrong/no-op rule and nothing proves the
  verdict would change; it could be tautological.
- `obs.log_run` has no **environment guard** against writing the production ledger under test, and
  renders missing values as `0` — both are the documented `tests-pollute-the-real-telemetry-ledger`
  bug. The probe also runs on **one** model, not the cheapest the factory will use.

---

## APPLY BACKLOG (prioritized)

Status: ✅ done · ▶ next (cheap + targets a documented bug) · ○ later. Each row names the AREA bug/
memory it targets.

**Applied 2026-10-30 (branch `feat/superpowers-merge`):** P0 ✅ · P1 ✅ · P2 ✅ · P3 ✅ · **P4 resolved**
— already covered on AREA's native *single-agent* path by the locked holdout + the `guard_holdout.py`
PreToolUse hook (the builder cannot edit the oracle). "Withhold the Agent tool from the builder" only
bites in a *multi-agent engine* where a builder subagent could spawn its own reviewer — i.e. the
`saas-coordinator-runner`/ACP path — so it is deferred there, **not** added as an inert `tools:` field
on main (that would reproduce the [[a-capability-threaded-through-one-entrypoint]] bug). P5–P11 remain ○.

| # | Apply to AREA | Source | Targets | Effort | Status |
|---|---|---|---|---|---|
| P0 | **Skill-description lint** in the gate: must start "Use when", no workflow verbs/arrows, word cap — and fix `authoring-area-skills`'s own description | discovery.md | discoverability; self-caught defect | XS, deterministic | ▶ |
| P1 | **`obs.log_run` environment guard**: refuse to write the prod ledger under pytest/non-prod; render missing as "unknown" not 0 | defense-in-depth, session-discovery | [[tests-pollute-the-real-telemetry-ledger]] (108 fake rows) | XS, deterministic | ▶ |
| P2 | **Mutation-check `wording_probe`**: a no-op / deliberately-wrong rule must flip the verdict, else the gate is tautological | writing-good-tests | proves the Tier-1 gate isn't theater | S | ▶ |
| P3 | **Compaction-proof task ledger** `tools/task-done.sh` (append only on green holdout + `verify-holdout-intact` exit 0) + resume check in build-from-docs | task-done/resuming | [[area-fix-loop-stale-oracle]], never re-build done work | S–M | ▶ |
| P4 | **Deterministic separation-of-duties**: withhold the Agent tool from `builder`/`holdout-fixer` profiles (tool-allowlist) so the builder *cannot* spawn its own grader — stronger than superpowers' prose ban; add "orchestrator never edits code" + "no early adjudication" to area-oracle-loop | implementer-prompt, fix-loop | [[a-guard-can-disable-another-guard]]; spine | S–M | ▶ |
| P5 | **Citation-grounded post-mortem** format for `docs/self-audit-*`: finding needs `path:line` into runs.jsonl/transcript/gate output; discard ungrounded; add a **claim-vs-tool-result** check ("gate passed" with no gate run = finding) | diagnosing-superpowers | [[area-fix-moves-decision-not-measurement]] | M | ○ |
| P6 | **Independent builder-check** on `acceptance.yaml` + docs 01–04 at intake, before the holdout author starts; wire to `validate-spec.sh` (ranked questions or "nothing important left") | builder-check-prompt | locking an oracle against an underspecified spec | S | ○ |
| P7 | **Blind-reviewer contract** for a review/audit kind: "report = unverified claims", "rationale never downgrades severity", **"Declined to judge"** channel → `_CHALLENGE.md`/Tung | task-reviewer, code-reviewer | self-grading in any LLM-review stage | M | ○ |
| P8 | **Scoped re-review + range guard**: `tools/review-package.sh` (reject HEAD not descendant of BASE, empty range); per-fix-round re-review keyed to the fix diff | re-review, review-package | fix loops that never converge | S–M | ○ |
| P9 | **"Rulings I made" disclosure** at end of build-from-docs: every autonomous judgment call surfaced to Tung | final-review/finish | spine: Tung is top gate | S | ○ |
| P10 | **Pressure-scenario library** for `wording_probe` (forced A/B/C, 3+ pressures, machine-parseable) covering AREA's real temptations (tweak the holdout, skip e2e, self-grade); store the control's verbatim excuses in the attestation; probe the **cheapest** model the factory uses | testing-skills-with-subagents | makes the Tier-1 gate reusable + deterministic grading | M | ○ |
| P11 | **No fixed sleeps** in generated e2e/chaos tests — use a `waitFor(cond, timeout)` helper | condition-based-waiting | flaky generated UI tests | S | ○ |
| — | ✅ fix-cause/3-strike/Review Focus (Tier-0); authoring-area-skills + wording_probe + inconclusive (Tier-1) | systematic-debugging, writing-skills | [[area-fix-moves-decision-not-measurement]] | done | ✅ |

**Do NOT import:** the multi-harness tool-map files, the packaging/loader sprawl, the visual-companion
server, prohibition-style bulletproofing for format/omission failures, and — above all — superpowers'
**n=1 self-graded validation method** (AREA's locked holdout + 5-rep probe is the stronger standard).

## Suggested order

**▶ P0–P4 first** — each is cheap/deterministic and targets a *documented* AREA bug or the spine.
P0/P1/P2 are XS–S and independent. P3/P4 harden the build loop. P5–P11 are the larger, later wins.
Everything that edits a skill/prompt goes through `authoring-area-skills` (probe before commit, clean
control) — but note weakness #2: do not adopt superpowers' habit of letting the editing model grade
its own rewrite.
