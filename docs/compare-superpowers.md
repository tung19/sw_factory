# AREA × superpowers — careful comparison and an optimal merge

Compared against `obra/superpowers` @ `main` (cloned 2026-10-30). Grounded in both codebases,
not marketing. AREA figures: `area/` ≈ 14k LOC, 896 test functions in 102 files, 16 agent-kind
profiles. superpowers: 15 markdown skills + a SessionStart bootstrap hook, no engine.

---

## 1. The one thing to understand first: they are different *layers*, not rivals

- **AREA** disciplines the **object layer** — the app being built. Its mechanism is *mechanical*:
  an acceptance oracle authored by a **separate** subagent from the spec only, **checksum-locked**
  (`tools/lock-holdout.sh`), tamper-checked after every build attempt (`verify-holdout-intact.sh`),
  blocked from editing at the editor level (`.claude/settings.json` → `guard_holdout.py`), and
  gated by **deterministic, non-LLM** checks + provenance (`gate.sh`, `provenance.sh`).

- **superpowers** disciplines the **meta layer** — *how the agent works*: brainstorm → plan →
  TDD → review → finish, plus how its own skills are written, triggered, and graded. Its mechanism
  is *exhortation*: Iron Laws, rationalization tables, red-flags, "violating the letter is violating
  the spirit", and fresh-subagent reviews. No checksum, no lock, no provenance.

> **superpowers is strong exactly where AREA is weak, and vice-versa.**
> AREA's own skills, prompts, and `CLAUDE.md` were written by one mind and never behaviorally
> tested — `area/evals.py`'s own docstring admits *"every factory change was adopted on vibes."*
> That is the meta layer, and it is precisely what superpowers has engineered. Meanwhile AREA's
> locked, independent, deterministic oracle is precisely what superpowers lacks — its TDD still
> lets **one agent write the test and the code**, held apart only by prose.
>
> The merge is therefore not a compromise. Each covers the other's blind spot.

---

## 2. Head-to-head (grounded)

| Dimension | superpowers | AREA | Winner |
|---|---|---|---|
| Scope | Any task, any codebase (incl. large existing) | Greenfield app factory only | superpowers (breadth) |
| Form / weight | ~15 markdown skills + 1 hook; nothing to maintain | 14k-LOC engine + 4 skills + 16 profiles | superpowers (lean) |
| TDD / oracle | RED-GREEN by the **same agent**; independence = prose | Oracle authored by a **separate** subagent, **checksum-locked**, edit-blocked | **AREA** |
| Gate | LLM-written review ("Critical blocks") | **Deterministic** audit + NFR + provenance | **AREA** |
| Supply-chain / provenance | None | spec digest → gates → artifact sha, fail-closed deploy | **AREA** |
| Domain depth | None (deliberately generic) | vinext/CF, CVE gate, node:sqlite resolution | **AREA** |
| End state | Branch merged / PR | Deployed app on your infra | **AREA** |
| **Skill triggering** | SessionStart hook force-injects "check skills first", survives compaction | PreToolUse *guard* only; no discovery bootstrap | **superpowers** |
| **Grading its OWN changes** | writing-skills: cheap subagent pressure-test (RED/GREEN) + wording micro-test | evals.py: expensive matched-pair outcome eval, ~$71/baseline, "insufficient-data" on every edit (M9) | split — see §4 |
| Distribution / ecosystem | 2-command install, huge adoption | Single-user, bespoke | superpowers |
| Multi-harness | Muse/Pi/Hermes/Antigravity/Codex/Copilot | Claude Code native only | superpowers |

**Honest read.** AREA wins the *object layer* decisively and that is its moat — keep it.
superpowers wins the *meta layer* (triggering, skill-authoring discipline, breadth, lean form).
AREA's documented bug classes are nearly all meta-layer failures: *"a fix that moves the decision
not the measurement"*, *"gate prints BLOCK then returns PASS"*, *evals priced out of a verdict*,
*holdout shared-dir race*, *stale oracle mid-loop*, *capability wired through one of four
pipelines*. superpowers has crafted, battle-tested answers to most of those shapes.

---

## 3. What each superpowers skill offers AREA (reuse map)

| skill | Reusable mechanism | AREA target | Fixes / addresses |
|---|---|---|---|
| **systematic-debugging** | "No fix without root cause"; **3+ failed fixes → STOP, question architecture**; never patch the symptom to make the gate go green | build/fix loop + `area-oracle-loop` | the #1 bug class *"fix moves the decision not the measurement"*; budget thrash |
| **writing-skills** | TDD-for-process-docs: baseline a fresh subagent **without** the skill (RED) → write to kill the rationalizations (GREEN) → close loopholes; **micro-test wording vs a no-guidance control, 5+ cheap reps**; "Match the Form to the Failure" taxonomy | a new skill-authoring discipline + cheap front-gate before `evals.py` | the "adopted on vibes" gap; makes `evals.py` affordable (M9) |
| **writing-plans** | **"Review Focus"**: enumerate every spec-implied input / failure mode that **no** test covers, force each into a test | `holdout-author` profile / `area-oracle-loop` | holdout happy-path bias; "spec silence ≠ permission to break" |
| **verification-before-completion** | claim → required **fresh** evidence table; "agent said success → verify the VCS diff, not its word" | `gate.sh` stages + `CLAUDE.md` | honesty-slice (BLOCK-but-PASS); no stage trusts a subagent's say-so |
| **subagent-driven-development** | Separation of duties: implementer may **not** grade or spawn its own grader; controller may **not** pre-judge the reviewer ("prompt says 'do not flag' → stop"); model-tier the judge above the builder | any LLM-review stage; profile model tiers | sharpens AREA's own spine into an explicit rule |
| **brainstorming** | HARD-GATE design doc + an **independent builder-check** subagent that must plan from the spec alone | pre-lock **spec-completeness gate** (before `lock-holdout.sh`) | locking an oracle against an underspecified spec |
| **using-git-worktrees** | Per-build isolated, **verified-ignored** scratch dir + green baseline before work | per-app build sandbox | *holdout shared-dir race*; ties to Group 3 isolation |
| **executing-plans** | Compaction-proof **ledger** (`progress.md`); completion line written only on green | run-loop resume / idempotency | *stale oracle mid-loop*; never re-build done work after a reset |
| **finishing-a-development-branch** | Re-verify on the **exact merged artifact**, not an earlier green run; human-gated integrate/destroy with a typed `discard` token | deploy stage, complements provenance | promoting on stale evidence |
| **using-superpowers** | SessionStart bootstrap: "1% chance a skill applies → you MUST invoke it", survives compaction | an AREA bootstrap hook | AREA's own skills don't reliably fire |
| **diagnosing-superpowers** | Transcript post-mortem; **"no path:line, no finding"**; independent per-dimension analysts; scrub re-audited until CLEAN | the `self-audit` / `deep-audit` docs | self-audits are currently self-asserted prose |
| requesting / receiving-code-review | Reviewer gets only {desc + reqs + SHA-range}, never session history; verify-before-implement + YAGNI | future LLM-review; build→fix loop | judge blind to builder's self-justification; cargo-culted fixes |
| dispatching-parallel-agents | "All dispatches in one response = parallel" + mandatory post-merge full-suite re-run | multi-app fan-out (minor today) | — |
| test-driven-development | Iron Law + the best-crafted rationalization tables in the set | see §5 — governs AREA's **own** engine | — |

---

## 4. The highest-value insight: stack the two "grade yourself" mechanisms

AREA already has `area/evals.py` — it stamps `(kind, digest)` on runs and compares **matched pairs**
of outcome metrics. It is correct but **priced out of a verdict**: one skill edit re-versions 7/16
kinds, and at `MIN_RUNS=5` regaining a baseline costs ~12 builds (~$71), so it returns
`insufficient-data` the moment you touch anything (memory: *area-evals-priced-out-of-a-verdict*, M9 open).

superpowers' `writing-skills` is the **missing cheap front-end**:
- Pressure-test the *wording change* against fresh subagents (with/without the edit) and micro-test
  5+ single-shot reps vs a no-guidance control — **cents, not $71**.
- It catches "does the prose actually *bind* the agent" — which `evals.py` cannot see at all.

**Stack them:** a prompt/skill edit must pass the cheap `writing-skills` behavioral gate first;
only edits that survive it spend the expensive `evals.py` matched-pair outcome eval. That makes
the factory's self-grading both honest (behavioral + outcome) and affordable.

---

## 5. The optimal blend — division of labor (the "tối ưu")

Give each layer the discipline best suited to it; stack cheap graders in front of expensive ones.

| Layer being changed | Discipline that governs it |
|---|---|
| An **app AREA builds** | **AREA oracle-loop** (locked, independent, deterministic). *Keep — the moat.* |
| **AREA's own 14k-LOC engine** | **superpowers TDD** (object code, no app-holdout → the right tool here; 896 tests already) |
| **AREA's skills / prompts / profiles / CLAUDE.md** | **superpowers writing-skills** (currently ungoverned → "vibes") |
| **Outcome confirmation of a factory change** | **AREA `evals.py`**, gated *behind* the cheap writing-skills test |

Reject: superpowers' same-agent TDD **for the apps AREA builds** (AREA's locked oracle is strictly
stronger) and its LLM-review **as the deploy gate** (AREA's deterministic gate + provenance is
stronger). Use superpowers TDD/review only for AREA's own engine code.

---

## 6. Proposed implementation order

**Tier 0 — cheap, safe, targets documented bugs (recommended first):**
1. Fold **systematic-debugging**'s root-cause rule + **3-failed-fixes circuit breaker** + "never
   patch the symptom to green the gate" into `area-oracle-loop` and the build/fix loop.
2. Add **writing-plans' "Review Focus"** step to the `holdout-author` profile — after covering every
   AC, force a test for each spec-implied input/failure mode that no AC covers.
3. Add **verification-before-completion**'s claim→fresh-evidence checklist to `gate.sh` stage
   boundaries and `CLAUDE.md` (no stage reports built/deployed on a subagent's word).

**Tier 1 — the meta-layer structural win:**
4. Author an AREA **`writing-skills` discipline** (its own skill) and wire the cheap behavioral
   wording-test as the front gate to `evals.py` (unblocks M9).
5. Add a **SessionStart bootstrap hook** so AREA's skills fire reliably and survive compaction.

**Tier 2 — fill the greenfield-only narrowness:**
6. **brainstorming** → a pre-lock spec-completeness gate (independent builder-check).
7. **using-git-worktrees** → per-app build isolation (fixes shared-dir race; Group 3).
8. **executing-plans** ledger → run-loop resume/idempotency.
9. **finishing-a-development-branch** → human-gated, re-verified deploy integration.

Each adopted skill must itself pass the Tier-1 `writing-skills` test before it lands — i.e. the
merge is performed under the discipline it installs.
