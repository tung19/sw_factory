---
name: authoring-area-skills
description: Use when editing any AREA skill, agent prompt, profile, or CLAUDE.md — i.e. changing how the factory ITSELF behaves. Pressure-test the wording against a fresh subagent (cheap) BEFORE spending on `area evals` outcome runs, and never let the same reasoning write and grade a factory change.
---

# Authoring AREA's own skills, prompts and profiles

Editing an AREA skill, an agent prompt (`prompt_sources` in a `profiles/*.yaml`), a profile
knob, or `CLAUDE.md` is **changing the factory's behavior**. The spine applies to the factory
itself: *never let the same reasoning write AND grade.* A change you wrote and then eyeballed
as "clearer" is ungraded — `area/evals.py`'s own docstring is the confession: *"every factory
change was adopted on vibes."* This skill is how a factory change earns its way in.

This is **TDD applied to process text** (adapted from `obra/superpowers:writing-skills`). You
write the test (a pressure scenario), watch a subagent fail without your edit, make the edit,
watch it comply, then close loopholes.

## The Iron Law

```
NO FACTORY-TEXT EDIT SHIPS WITHOUT A CHEAP WORDING-PROBE FIRST
```

The probe is cheap (cents, a few subagents) and catches the failure `area evals` **cannot
see**: whether the words actually *bind* the agent. `area evals` is the expensive second gate
(matched-pair outcomes, ~$71/baseline, and `insufficient-data` the moment a digest changes —
that is M9). Stack them: **probe first, evals second.** Spending the dear gate on wording a
subagent ignores is the waste the probe removes.

## Two gates, in order

1. **Cheap wording-probe (this skill).** Does the edited text change behavior under pressure?
   Runs natively with the `Task` tool — no API key, no `area/engine`. Record the verdict with
   `area wording-probe record <kind> …`; `area evals` then shows it per kind.
2. **Expensive outcome eval (`area evals`).** Only for a change the probe says *binds*: do
   real runs improve outcomes over the previous version on the declared task set?

## The cheap probe — exact protocol

1. **Classify the baseline failure first.** You cannot bulletproof a failure you have not
   seen. Name the tempting scenario (the pressure that makes an agent cut the corner).
2. **No-guidance control (RED).** Spawn a fresh `Task` subagent with the realistic context
   **minus** your edit, and the tempting task. Record its behavior and its exact
   rationalizations, verbatim. *If the control does not exhibit the failure, stop — there is
   nothing to fix, do not add the words.*

   > **The control must be CLEAN, or it is not a control.** An in-session `Task` subagent
   > inherits this repo's `CLAUDE.md`. If the text you are probing — or an earlier copy of
   > it — already lives in `CLAUDE.md`, the "control" silently has the guidance and the whole
   > probe is confounded. Tell-tale: the control cites a rule or a name your prompt never gave
   > it (e.g. "Tung", or the exact phrase you just wrote). So **probe BEFORE you commit the
   > edit into `CLAUDE.md`**; or remove it from `CLAUDE.md` on disk for the run; or probe
   > out-of-session (raw API / a project with no `CLAUDE.md`). A confounded run is recorded
   > `--inconclusive`, never `--binds`.
3. **With-guidance (GREEN).** Spawn the same scenario **with** the edited text in context.
   Confirm it now complies.
4. **5+ reps per arm. Read every output by hand.** Single samples lie; template echoes and
   quoted counter-examples masquerade as hits. **Variance is the metric** — when wording
   binds, reps converge on the same shape; five different readings mean it does not bind yet.
5. **Record:** `area wording-probe record <kind> --binds "<evidence>"` (or `--weak`, or
   `--inconclusive` for a confounded run). The attestation is keyed to the profile's
   **current digest**, so it is invalidated automatically the next time that prompt/skill
   changes.

## Match the form to the failure

The form that bulletproofs one failure type backfires on another (from superpowers:writing-skills):

| Baseline failure | Right form | Wrong form |
|---|---|---|
| Skips a rule under pressure (knows better, does it anyway) | Prohibition + rationalization table + red-flags | Soft "prefer/consider" |
| Output has the wrong shape (bloated, buried verdict) | Positive recipe: state what the output IS, in order | A prohibition list |
| Omits a required element it already produces | Structural: a REQUIRED slot in the template | Prose reminders near the template |
| Behavior should depend on a condition | Conditional on an **observable predicate** | Unconditional rule + exemption clauses |

**No nuance clauses, no exemption clauses** — "don't X unless it matters" reopens the
negotiation and measurably degrades a winning recipe. Express a real exception as its own
conditional on something observable.

## Rationalizations — STOP, these mean you are skipping the probe

| Excuse | Reality |
|--------|---------|
| "It's just a wording tweak" | Wording is the whole mechanism of a discipline skill. Probe it. |
| "Obviously clearer to me" | Clear to you ≠ binding on another agent. The probe is the only evidence. |
| "evals will catch it" | evals can't see binding, costs ~$71, and says insufficient-data on every edit. |
| "No time / too tedious" | The probe is cents and minutes; a factory change adopted on vibes costs every build after. |
| "I'll record the probe later" | Then it shipped untested. Record before you promote the edit. |

## What this does NOT cover

Pure reference text (API paths, command syntax) with no behavior-shaping claim — there is
nothing to bind, so no pressure-probe is required (a retrieval check is enough). Everything
with a "you MUST / never / always / STOP" is a discipline edit and takes the probe.

## Checklist (one todo per item)

- [ ] Named the tempting scenario and the baseline failure
- [ ] Ran the no-guidance control; it exhibited the failure (else stop)
- [ ] Ran with-guidance; it complied
- [ ] 5+ reps per arm, every output read by hand, variance low
- [ ] Control was CLEAN — not inheriting the edit via CLAUDE.md (else record --inconclusive)
- [ ] Form matches the failure type (table above)
- [ ] `area wording-probe record <kind> --binds/--weak/--inconclusive "<evidence>"`
- [ ] Only then: `area evals <kind> --check` for the outcome gate
