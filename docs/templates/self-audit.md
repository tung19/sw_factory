# Self-audit — citation-grounded format (P5)

Use this shape for any `docs/self-audit-*.md`. Adapted from superpowers:diagnosing-superpowers.
The rule that makes an audit trustworthy: **evidence, or it is not a finding.** A self-audit
written as prose assertions is the same reasoning grading itself — the thing AREA's spine forbids.

## Hard rules

1. **No `path:line`, no finding.** Every finding cites a concrete location — a source file
   (`area/foo.py:123`), a ledger row (`workspace/.area/runs.jsonl:NN`), a gate output line, or a
   transcript line. A claim with no citation is **dropped**, not softened.
2. **Quote, don't paraphrase.** Include the ≤200-char quote the citation points at, so a reader
   verifies without re-deriving.
3. **Numbers come from a command or a file, never memory.** Show the command.
4. **Diagnose, don't prescribe in the same breath.** State the defect and its evidence; the remedy
   is a separate decision (Tung's gate). A finding that smuggles in "so we should rewrite X" is
   doing two jobs and hides the evidence for the first.
5. **Claims-vs-reality is itself audited.** Every "passed / fixed / deployed / green" assertion in
   the thing under audit must cite the tool result or gate run that PROVED it. A success claim with
   no backing run is a finding (the `fix-moves-the-decision-not-the-measurement` class: a gate that
   prints BLOCK then returns PASS, a run recorded `passed=True` with no verifier).

## Finding block

```
### F<n> · <one-line defect> · <severity: blocking|high|medium|low>
evidence: <path>:<line> — "<quote ≤200 chars>"
repro:    <exact command, if any>
claim-vs-reality: <what it asserts> vs <what the cited run/output actually shows>
status:   OPEN | for Tung | fixed in <commit>
```

## Claims audited (table)

| Claim in scope | Backing run / tool result (path:line) | Verdict |
|---|---|---|
| "gate X passed" | runs.jsonl:NN / gate output:LL | backed / **UNBACKED → finding** |

An audit with an empty "Claims audited" table did not run rule 5.
