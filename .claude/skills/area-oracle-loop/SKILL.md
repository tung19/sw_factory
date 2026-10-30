---
name: area-oracle-loop
description: AREA's build discipline — lock an INDEPENDENT acceptance-test oracle BEFORE writing code, then build to "oracle green" and never let the model judge its own work. Use whenever building or fixing an app inside the AREA factory (any run / clone / iterate / intake build), especially a --tdd build.
---

# AREA oracle-loop

AREA's backbone is a **process, not tooling**: an oracle-driven convergence loop.
Product quality ≤ oracle quality. Your job is to make the app pass a **strong,
independent, runnable oracle** — not to "look done".

## Non-negotiable rules

1. **The oracle comes BEFORE the code.** In `--tdd` mode an independent verifier
   has already written and **checksum-locked** the acceptance tests under
   `__tests__/_holdout/` (+ `CONTRACT.md`). Treat them as the spec. Build the app
   to make them pass.
2. **Never weaken the locked tests.** The fixer (you, when building) must not edit,
   delete, mock-away, or loosen anything under `__tests__/_holdout/`. The loop
   converges only to those tests passing for real.
3. **No self-judging.** "Done" = the oracle (holdout + whatever gates are on:
   audit / e2e / chaos / parity) actually passes when run. It is never your own
   assertion that the work looks correct — nor a subagent's or a tool's *report* that
   it passed. Read the real command output, the exit code, the actual diff yourself; a
   claim of success is not evidence of success.
4. **If a locked test is genuinely wrong**, do not silently fight it. Write your
   case to `__tests__/_holdout/_CHALLENGE.md` (the one file excluded from the
   lock). An independent verifier re-adjudicates it against `acceptance.yaml` and
   either corrects + re-locks or rejects it. Then one bounded rebuild follows.
5. **Clone / reverse-engineer mode: the reference app IS the golden oracle.**
   "Perfect" = behavioral parity (same input → same output). Derive and match the
   reference's observed behavior; do not invent behavior it doesn't have.
6. **Fix the cause, never the measurement.** A failing gate or holdout test is a
   *measurement*. Make the app genuinely satisfy it — never edit the gate, loosen or
   delete an assertion, special-case the test's input, or add a branch that only fires
   under test, to turn the light green. A "green" produced by changing what green *means*
   is AREA's single most common self-inflicted bug. Can't pass it honestly? That is a
   signal to re-investigate or escalate (see Stop conditions), not to reshape the oracle.

## When you are the one AUTHORING holdout tests (verifier role)

The directory is EMPTY and the app does not exist yet. **Create the test files
NOW — do not explore the repo first.** (In clone/parity mode the only read
allowed is `./_sample`.) The output must:

- cover **every** acceptance-criterion id (one+ assertion per AC — not just one
  happy-path test),
- include real assertions (`expect(...)`),
- define the module contract in `CONTRACT.md` (exact import paths + signatures),
- match the exact numbers in the acceptance examples bit-for-bit,
- **Review Focus — test past the happy path.** Once every AC has an assertion, list the
  inputs and failure modes the spec *implies* but names no AC for — empty / missing /
  malformed input, boundary values, auth absent, duplicate or concurrent action, the
  negative of a rule stated only positively — and add a holdout test for each. Spec
  silence is not permission for the app to misbehave; a happy-path-only oracle certifies
  a brittle app as "done".

Wandering to "understand the system" before writing a single test is the main
failure mode here; resist it.

## Stop conditions (don't loop forever)

Stop when the oracle is green, or a budget/iteration cap is hit. Otherwise apply the
**3-strike rule**: once the SAME failure has survived three honest fix attempts, STOP
patching — a fourth variation of the same fix is almost never the answer; the hypothesis
or the architecture is. Re-investigate from the root (read the real error, reproduce it,
trace the data flow backward to its source), or escalate to Tung. Burning quota against
an unsatisfiable or wrong oracle is a spec problem for a human to resolve, not something
to grind on.
