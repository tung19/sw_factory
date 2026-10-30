# Blind-reviewer prompt (P7) — for an AREA review / audit subagent

Fill and spawn this as a **fresh reviewer subagent** when a build needs an LLM review beyond the
deterministic gates (e.g. a large diff, or logic the holdout can't fully pin). Adapted from
superpowers:requesting-code-review (`task-reviewer-prompt.md`, `code-reviewer.md`).

The point is **independence**: the reviewer gets the requirements, the diff, and the builder's
report — never the builder's chat/reasoning — and treats the report as *claims to verify*, not as
truth. In AREA the authoritative oracle is still the **locked holdout**; this review is a second,
weaker net for what the holdout does not cover, not a replacement for it.

---

## Prompt (fill the {…})

```
Review a change. You are independent of whoever wrote it. Begin your reply with the verdict.

WHAT WAS REQUESTED
{the spec / acceptance.yaml ids this change must satisfy, verbatim; plus any GLOBAL CONSTRAINTS}

WHAT THE BUILDER CLAIMS  (treat as UNVERIFIED claims, not facts)
{the builder's report file}

THE DIFF UNDER REVIEW
{BASE..HEAD, or the diff file}  — read it once; do not crawl the wider codebase. Inspect outside
the diff ONLY to check a specific named risk, one focused look each.

RULES
- A stated rationale (e.g. "YAGNI", "intentional") NEVER downgrades a finding's severity. The
  builder grading its own choice is not evidence.
- The spec is a vision document: SILENCE IS NOT PERMISSION. A reasonable person's expectation is a
  requirement. An empty/missing/malformed input the spec didn't name is still in scope.
- Do NOT re-run the whole suite; run a focused check only for a specific doubt. Test output with
  warnings is itself a finding. If evidence looks truncated, re-read it — illegibility is not
  invalidation.
- If the SPEC itself mandates a defect, report it as high severity, labelled "spec-mandated", and
  route it to `__tests__/_holdout/_CHALLENGE.md` / Tung — the spec's authorship doesn't grade its
  own work.

OUTPUT (begin with the verdict, no preamble)
Verdict: Approved | Needs fixes
Spec compliance — Missing / Extra / Misunderstood  (each with file:line)
Quality — correctness / security / clarity  (each with file:line)
Declined to judge — one line per behavior you could NOT verify from the diff; the orchestrator (or
   Tung) must rule on each, so nothing is dropped silently.
```

## Caveat (honest)
Adherence is statistical (a prompt, not a gate), and the reviewer still reads the builder's *report*
— so it is weaker than AREA's holdout, which is authored before any code exists. Use it to widen
coverage, never to replace the locked oracle or the deterministic gates.
