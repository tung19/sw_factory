# ADR 0003 — The oracle-loop: an independent, locked acceptance oracle

Status: **Accepted**

## Context

An AI that writes code and then judges its own code gives no real assurance — the
same reasoning that made a mistake will tend to miss it when grading. Most "AI
coding agent" tools build *to a vague "looks done"*, which is unauditable and
drifts. AREA needs a convergence target that is **strong** and, crucially,
**independent** of the implementer.

## Decision

Quality is bounded by **the strength + INDEPENDENCE of the oracle**:

1. Before any implementation exists, a **separate agent** authors acceptance tests
   (the *holdout*) from the spec ONLY, under `__tests__/_holdout/`.
2. Those tests are **checksum-locked** (`tools/lock-holdout.sh` →
   `specs/<name>/holdout.lock`). The build agent may never edit them — enforced in
   code by a PreToolUse hook (`tools/hooks/guard_holdout.py`) and re-checked by
   `tools/verify-holdout-intact.sh`.
3. The build loop converges to **"oracle green"** — the locked suite passes AND is
   confirmed to have actually executed (`area/verify/_runners.py`), not merely
   exited 0 — then stops.
4. If the builder believes a locked test is genuinely wrong, it writes a
   `_CHALLENGE.md`; an **independent verifier** re-adjudicates and re-locks. The
   builder can never silently change the oracle.
5. The human (the repo owner) is the top gate for the one question the loop can't
   answer: *"is the oracle itself correct?"* — a spec question.

Additional, independently-run gates (`audit`, `e2e`, `chaos`, `nfr`, `perf`,
`product`) harden the build; of these, only the holdout is a *fully independent*
oracle — `e2e`/`chaos`/`audit` use the implementer-style agent and are hardening,
not independent checks (stated plainly in the docs so they aren't over-trusted).

## Consequences

- **Positive:** builds are auditable (spec digest → locked oracle → gates →
  provenance), the self-certification failure mode is structurally prevented, and
  "done" has a concrete, testable meaning.
- **Cost:** authoring + locking an independent suite adds an agent stage and some
  latency/cost per build; a too-weak oracle still caps quality (hence the human
  gate on oracle correctness, and `--clarify`/spec-review at the spec stage).
- **Scope:** this is the invariant everything else serves; changes to `area/verify`,
  the engine seam, or `tools/` must preserve it (see `CONTRIBUTING.md`).
