# AREA vs. Harness² — recursive agent harnessing

Measured 2026-10-28 against **Harness²: Recursive Agent Harnessing for an Open World**
(Google, [arXiv:2610.14224](https://arxiv.org/abs/2610.14224), open-sourced ~2026-10-18),
read in full including appendices D–H.

Companion to [`secure-factory-gap-assessment.md`](secure-factory-gap-assessment.md),
which closed the question *"who grades a change to the factory?"* (Group 4 → `area evals`).
Harness² asks the next one: **who proposes it?**

One line up front: **do not install Harness², and do not adopt its verification posture —
that would be a downgrade. Adopt its object of improvement, its evidence rule, and its
ablation ranking.** The paper's own stated weakness is the exact thing AREA's spine exists
to prevent.

## What Harness² actually does

It edits the scaffolding around a model, never the weights. **K = 8 editable components:**
system prompt · guardrails · memory · skills · tool guidance · scripts · subagents ·
middleware plugin. Four are always-on text; the rest act on demand or inside the tool loop.

Two recursion levels:

- **Task-level — Propose · Probe · Compose.** *Propose* emits two candidates: one
  **invariant** (a recurring agentic weakness — planning, tool use, context management,
  delegation) and one **domain-specific** (what a practitioner of this domain knows).
  *Probe* runs a reference execution of the current harness on the task, then each
  candidate on **the same task under matched model and environment**, and compares
  trajectory + deliverable to produce a **behavioural contrast**. *Compose* reads the
  reference, the candidates, their diffs and the task-local evidence, and may merge,
  revise, adopt one, or keep the current harness — each decision tied to a concrete
  observation rather than an assumed score gain. "Contrastive" means judged by
  *difference from the reference run*, not by correctness.
- **Harnessing-level.** After the deliverable, the whole improvement record is reviewed and
  lessons extracted into a library: each entry is an **executable harness plus an
  `EXPERIENCE.md`** (applicable situation, lessons, supporting evidence), with an **index**
  for later lookup. **Lessons are kept only when execution contrasts support them; on
  insufficient evidence, no entry is added.**

**Results.** Benchmarks WorkBuddy-Bench, JobBench, LAB; models GLM-5 and Gemini 3.5 Flash.
Gains up to 11.5 / 4.5 / 11.8 points over each model's base harness, rising with the
recursion budget.

**The ablation is the most useful table in the paper** — components removed from the
*already-improved* harness, averaged over three domains:

| Configuration | Avg. |
|---|---|
| Base harness | 72.4 |
| Full Harness² | **80.8** |
| w/o prompt components | 79.3 (−1.5) |
| w/o scripts | 77.1 (−3.7) |
| **w/o skills** | **75.5 (−5.3)** |

Skills are the single biggest lever — bigger than prompts and scripts combined.

**And the paper's own limitation, verbatim (Appendix F):** *"Without ground-truth
supervision, refinement relies on behavioural contrasts and model judgment, which can
share model biases."* Its honest failure data agrees: ReasoningBank drops up to **6.6
points below base** on coding tasks, and Harness Scaling **underperforms base in 7 of 12**
benchmark–configuration pairs. Cost: roughly **4k rollouts per task** at parallel budget k.

## Where AREA stands — the 8 components mapped

| # | Harness² component | AREA | Verdict |
|---|---|---|---|
| 1 | System prompt | `area/build/nextjs.py` `_prompt_plain`/`_prompt_cloudflare`/`_COMMON_RULES`/`_TDD_PREAMBLE`, ~25 prompts total, all Python source, **source-hashed into the profile digest** | ✅ strong — versioned, not just editable |
| 2 | Guardrails | `.claude/settings.json` → `PreToolUse` → `tools/hooks/guard_holdout.py`: turns "please don't touch the locked oracle" into **cannot** | ⚠ **leaky — does not reach the build agent** (F3) |
| 3 | Memory | `area/memory/` → `WORKSPACE/.area/memory.jsonl`, auto-written, **injected into build + chaos prompts** | ❌ **ungated (F1)** |
| 4 | Skills | `skills/` — **2 skills, 160 lines**: `area-oracle-loop` (51, the INV component) + `vinext-cf-build` (109, the DOM component) | ⚠ **thinnest component, highest leverage (F2)** |
| 5 | Tool guidance | `area/skills.py:44 skills_preamble()` — 4 hardcoded blurbs; tools/MCP explicitly out of profile scope (`area/profile.py:29-31`) | ⚠ minimal |
| 6 | Scripts | `tools/*.sh` — `gate.sh`, `lock-holdout.sh`, `verify-holdout-intact.sh`, `provenance.sh`, `deploy.sh`, `verify-factory-intact.sh` | ✅ strong, deterministic |
| 7 | Subagents | Holdout author runs in a **fresh** subagent whose only input is the spec — CLAUDE.md enforcement (c) | ✅ **stronger use than the paper's**: independence, not just delegation |
| 8 | Middleware plugin | — | ✗ absent |

Also present and **not in the paper's list**, because the paper has no equivalent: a
**locked, checksum-frozen, independent acceptance oracle** (`area/verify/holdout.py`), and
a 9-gate registry (`_GATE_ORDER`) with a committed-budget → blocking posture rule.

## Findings of substance

### F1 · The evidence gate is on the write-back that cannot reach a prompt, and there is none on the one that can

AREA has **two** scaffolding write-backs. They are gated in exactly the wrong arrangement.

**(a) `profiles/<kind>.yaml: experience` — correctly gated, structurally inert.**
`area/evals.py:345 record_experience()` refuses unless `compare()` returns a verdict in
`DECISIVE = ("improved","regressed","ok")`; `unpaired`, `insufficient-data`, `no-data`,
`new-profile` all refuse, as does an empty note. It records `when`, `digest`, `verdict`,
the paired `tasks`, both sample sizes, the `deltas` and the note — a faithful and in fact
*stricter* `EXPERIENCE.md` than the paper's, since the paper gates on "contrasts support
it" while AREA gates on a quantitative verdict over matched pairs. `experience_index()`
is the paper's index.

Its entire read path is `area evals --notes` → **stdout**. It is never concatenated into
any prompt and never consulted by any gate. **No `experience:` block exists in any shipped
profile; zero lessons have ever been recorded** — and none can be, because every kind
currently grades `no-data` (see F6).

**(b) `area/memory/memory.jsonl` — ungated, and prepended to the top of the build prompt.**
The write (`area/engine/adapter.py:418-427`):

```python
if passed and used > 1 and first_fail:
    memory.remember(symptom=f"[{label}] {first_fail[:280]}",
                    tags=[label.split(':')[0], label])
```

The gate is *"the loop eventually passed and took more than one attempt"* — not evidence,
not a verdict, not a digest. `fix=` is never supplied, so **every auto-written entry has an
empty `fix`**. The read (`area/build/nextjs.py:252-261`) is applied **last**, i.e. it lands
at the very **top** of the build prompt, above the TDD preamble, under the header
`=== Known pitfalls from past runs (avoid these) ===`. `area/verify/chaos.py:50-52` does
the same for chaos authoring.

The live store proves the harm. 5 entries: 1 hand-written seed (a real lesson, with a real
`fix`), and **4 auto-written, all with `fix: ''`**:

| # | tags | what it actually is |
|---|---|---|
| 1 | `['spec','spec']` | `No such file or directory: .../workspace/specs/app/spec.yaml` — an **environment error** on a stale path, and `app` is the **test fixture's** name |
| 2 | `['audit','audit']` | raw `npm audit` output, truncated mid-table |
| 3 | `['build','build:plain:tdd']` | **the oracle's own tamper rejection**: `FORBIDDEN: files under __tests__/_holdout/ were modified…` |
| 4 | `['chaos','chaos']` | `No test files found, exiting with code 1` — a harness misconfiguration |

None is a lesson. Entry 3 is the worst category error: the enforcement message that *proves
the oracle worked* is recycled as domain knowledge and re-injected into every future
`build` prompt as something to "avoid".

Harness²'s rule is *keep a lesson only when execution contrasts support it; otherwise add
no entry.* AREA implemented that rule faithfully — and wired it to the path with no reader,
while the path that reaches the model has no rule at all.

Both halves say so in their own first line. `area/evals.py:338` introduces the gated one as
*"the evidence-gated experience log (**Harness2's one habit worth taking**)"*; the ungated
one is `area/memory/store.py:1`, *"experience store: remember pitfalls, **inject them into
prompts**"*. The habit was taken, and attached to the store that does not inject.

### F2 · AREA's highest-leverage component is its thinnest

The paper's ablation puts **skills first** (−5.3 when removed, vs −3.7 scripts and −1.5
prompts). AREA ships **160 lines across 2 skills** into every built app.

They are the right *shape* — `area-oracle-loop` is precisely an **invariant** component
("how the agent works": lock the oracle, never self-judge, don't wander before writing
tests) and `vinext-cf-build` is precisely a **domain** one ("what a practitioner knows").
AREA arrived at the paper's INV/DOM split independently. There is simply very little of it,
and the domain half covers exactly one domain.

Worth noting what this means for **M9** in [`self-audit-2026-10-27.md`](self-audit-2026-10-27.md):
the fix proposed there — scope the skills digest per kind/target so a Cloudflare skill stops
re-versioning the e2e author — **is** the paper's INV/DOM separation applied to versioning.
The two backlogs agree.

### F3 · The guardrail protects the interactive session, not the agent that writes the code

`guard_holdout.py` is a genuinely stronger guardrail than the paper's text files: it is a
mechanical `PreToolUse` block, exit 2, on any edit inside a locked `__tests__/_holdout/`.

But a built app's `.claude/` directory contains **only `skills/`** — measured on
`~/area-generated/apps/taskboard/`. No `settings.json`, no hook, and **nothing in `area/`
installs one** (`install_skills` copies skills and nothing else). So for the autonomous
build agent, holdout protection is **detection after the fact** (the oracle re-checks
checksums every run and refuses), not **prevention**.

Detection is mostly sufficient — a tampered holdout cannot produce a green build. But the
bug fixed in #33 is exactly the gap: `author_until` would silently re-author an
already-locked holdout **and rewrite its lock to match**, after which
`verify-holdout-intact.sh` still reported the oracle intact. Prevention would have blocked
that write; detection validated it.

### F4 · AREA can do the paper's probe *honestly*, and the paper cannot

This is the finding that decides the whole adopt/refuse question.

Harness²'s probe cannot say whether a candidate harness was **right** — only whether it
behaved **differently**. Its authors say so: no ground truth, so refinement leans on
behavioural contrast plus model judgment, "which can share model biases." That is why their
own numbers include a configuration that is *worse than base in 7 of 12 pairs*.

AREA's probe would have a **locked, independent, checksum-frozen acceptance oracle** as its
judge. Substituting the holdout for the behavioural contrast turns
"did behaviour change?" into "did the acceptance criteria pass?" — and AREA already has the
matched-pairs machinery (`area/evals.py:111 paired_tasks`, which cites this very paper at
`:19-25`), the attribution (`obs` stamps `profile`+`profile_digest`), and the task set
(`evals/tasks.yaml`, 3 tasks chosen *because* each has a locked oracle).

What is missing is only the **Propose** and **Compose** steps. AREA has the grader; it has
no proposer. Every factory change to date was proposed by a human.

### F5 · Smaller gaps

- **No per-kind model selection.** The paper varies model–harness configurations; AREA's
  profile schema has no `model` field (`area/profile.py:29-31`, `PLAN.md` §10 P5b record
  this as deliberately not yet wired). So "which model for which kind" is unversioned and
  ungraded.
- **Tool guidance is four hardcoded blurbs** (`area/skills.py:48-54`), and tools/MCP are
  explicitly outside the profile digest — so a tool change is invisible to `evals`.
- **No middleware/plugin component** (the paper's 8th).
- **`pass_rate`'s tolerance was calibrated against an inflated number.** `TOLERANCE`
  (`area/evals.py:50-55`) is calibrated on "110 runs: first-try 0.91, avg 1.12 attempts,
  $1.65/run", while the same module's docstring warns that ledger **over-reports passes**
  (`run_once` recorded `passed=True` with no verifier; 109 of 110 say they passed).
  `first_try_rate` is safe — it is computed only over convergence runs, which had real
  verifiers — but `pass_rate` pools the unverified ones, so its −0.10 threshold came from a
  ~0.99 pass rate that was not real.
- **Latent pollution, prompt-side.** `tests/conftest.py` guards `obs.RUNS` (see M8) but not
  `memory.MEM`. Today the suite writes nothing, but only because `memory.remember` requires
  `used > 1` and no current test both fails once and then passes. A future test of the
  retry path would silently inject records into a store that **feeds prompts** — strictly
  worse than M8, which only fed a gate.

### F6 · Everything above is measured on a factory whose outer loop has never run once

0 of 110 live ledger records carry a `profile_digest` or a `name`. So all 16 kinds grade
`no-data`, `paired_tasks` is always empty, `record_experience` refuses for every kind, and
no `experience:` block exists. `area evals` is complete, tested, and has never produced a
verdict — the same conclusion M9 reached from the cost side.

## Verdict

### Refuse

1. **Installing Harness².** AREA is not a harness looking for a loop; it is a loop with a
   harness. The framework's value is its *method*, and the method is five pages.
2. **Its verification posture.** Adopting behavioural contrast where AREA has a locked
   oracle would replace ground truth with model judgment — the one trade AREA exists to
   refuse. "Quality ≤ strength + independence of the oracle" forbids it.
3. **Its cost shape, unmodified.** ~4k rollouts per task against AREA's measured median
   **$5.94 / 15 min per build** is ~$24 and an hour **per task per improvement step**, on
   a factory that cannot yet afford 12 builds for a single verdict (M9).

### Adopt

Ordered by value ÷ cost. Each is small; none requires the framework.

1. **Fix F1 — put the gate where the reader is.** Two honest shapes: gate `memory.remember`
   the way `record_experience` is gated, or give `experience` the read path that `memory`
   has. Either way, what reaches a prompt must carry evidence, and what carries evidence
   must be able to reach a prompt. **The cheapest correct first move is smaller than both:
   a `fix`-less entry is not a lesson — refuse to store one.** That alone drops 4 of the 4
   auto-written entries, including the oracle's own FORBIDDEN message.
2. **Fix F3 — install the guardrail into built apps.** Write a minimal `.claude/settings.json`
   with the `PreToolUse` hook alongside `install_skills`, so prevention reaches the agent
   that actually writes code. Deterministic, agent-free testable, closes #33's class.
3. **Invest in skills (F2), using the INV/DOM split AREA already has.** This is the
   measured biggest lever in the paper and the thinnest component in AREA. It converges
   with **M9 option 1b**: scope the skills term per kind/target, and install only the
   skills a target can use. Do it now, while there is no baseline to invalidate.
4. **Propose–Probe–Compose with the holdout as the probe's judge** (F4) — the one genuinely
   new capability, and the only place AREA can beat the paper rather than copy it. Scope it
   narrowly: one task, one invariant candidate, one domain candidate, probe = the locked
   oracle plus `evals` metrics, compose = a human (Tung) reading a diff. Automate the
   proposer only after the grader has produced a single real verdict.

### What to grasp

- **The paper's contribution is the *object*, not the loop.** Improve the harness, not the
  model — and keep every edit tied to a concrete observation. AREA already versions its
  harness (profile digests); it does not yet edit it from evidence.
- **Its weakness is stated by its own authors**, and it is precisely AREA's reason to exist:
  no ground truth → shared model bias → a configuration that is worse than base in 7 of 12
  pairs. AREA's independence enforcement is the fix for the paper's central limitation.
  **AREA is not behind here; it is ahead, and should not trade down.**
- **The ablation tells you where to spend:** skills > scripts > prompts. AREA has this
  exactly inverted in effort to date.
- **"Insufficient evidence → no entry" is the paper's real discipline**, and it is the same
  rule as AREA's "a gate that cannot measure must not pretend it did". AREA already wrote
  that rule down twice (`evals.check`, the posture rule) and then broke it in the one place
  nobody was looking — the memory store (F1).

## Deliberately out of scope

Automating the **Compose** step, and any loop that edits `skills/` or a prompt `.py` file
without a human in the path. AREA's spine says the same reasoning must not both write and
grade; an agent that rewrites its own prompt and then grades the result with `evals` —
whose thresholds are also factory config — is that violation with extra steps. The human
stays in Compose until there is a measured baseline to argue otherwise.

## See also

- [`secure-factory-gap-assessment.md`](secure-factory-gap-assessment.md) — finding 3 ("the
  factory grades its own improvements") is what `evals` answered; this document is its sequel.
- [`self-audit-2026-10-27.md`](self-audit-2026-10-27.md) — **M9** (evals priced out of a
  verdict) and **M8** (the test suite polluting the ledger) are both load-bearing here.
- `area/evals.py:19-25` — already cites arXiv:2610.14224 for the matched-pairs probe.
