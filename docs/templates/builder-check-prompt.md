# Builder-check prompt (P6) — a spec-completeness probe before the oracle is locked

Spawn this as a **fresh subagent** at intake, AFTER `docs/01-engineering-intent.md`,
`02-product-requirements.md`, `03/04`, and `workspace/specs/<name>/acceptance.yaml` are drafted,
and BEFORE the holdout author starts. Adapted from superpowers:brainstorming/builder-check.

Its job is to catch the ambiguity that would otherwise be resolved by a silent guess during the
build — the guess that makes the locked oracle encode the wrong behavior. It is cheap: one
subagent, no build. It is **advisory**: if it returns material questions, STOP and ask Tung
(CLAUDE.md §0: "if a material ambiguity blocks a buildable spec, STOP and ask Tung").

> **Caveat (honest):** this is a same-model, fresh-context probe — it shares the author's blind
> spots and nothing stops a confident wrong guess from passing silently. It narrows ambiguity; it
> does not prove the spec complete. It is the cheap front; the locked holdout remains the oracle.

---

## Prompt

```
You are a talented engineer who has just been handed a specification to BUILD, with no
access to the person who wrote it. You cannot ask them anything during the build.

Read ONLY these files (do not explore the repo): <docs 01–04 + acceptance.yaml paths>.

Report ONLY the questions you would still need answered to build this correctly —
specifically, the places where you would have to GUESS and a wrong guess would change
what you build (behavior, data shape, an edge case, a number, an auth rule). For each:
  - the exact spec location that is silent or ambiguous,
  - the guess you would otherwise make,
  - why a wrong guess would matter.
RANK them, most-consequential first.

SKIP anything you could reasonably decide yourself without changing the product. If there
is nothing a wrong guess would get wrong, answer exactly: "nothing important left".
```

## Using the result
- `"nothing important left"` → proceed to lock the oracle.
- Any ranked questions → STOP, put them to Tung, amend the spec, re-draft, re-run this check.
  (Do not resolve them yourself and build on the guess — that is the failure this prevents.)
