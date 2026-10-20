# AI-DLC Inception artifact contract (PR8, Phase 0)

This freezes the **boundary** between the AI-DLC Inception front-end (which
*produces* artifacts) and AREA's intake adapter (which *consumes* them). The
front-end — whether AREA's own native Inception engine (PR8 Phase 1) or the real
[`awslabs/aidlc-workflows`](https://github.com/awslabs/aidlc-workflows) tool
(Phase 4 interop) — must emit artifacts that follow this contract so
[`area/intake/aidlc.py`](../area/intake/aidlc.py) translates them faithfully into
`spec.yaml` + `acceptance.yaml`, after which AREA's autonomous pipeline (`--tdd`,
gates, deploy) takes over unchanged.

The golden example of this contract is the fixture under
`tests/fixtures/aidlc/link-shortener/`, kept contract-compliant by
`tests/test_aidlc_contract.py`. Target that fixture when building a front-end.

## How the adapter reads artifacts (frozen behavior)

`load_aidlc_artifacts(path)`:
- `path` is a **file or a directory** (read **recursively, sorted by path**).
- Only text-ish files are included: `.md .markdown .txt .yaml .yml .json`. Other
  files are ignored.
- Each file is wrapped as a delimited block: `=== <relative/path> ===\n<contents>\n`.
- The combined blob is capped at **60 000 characters** (truncated at the boundary).
- Errors (raise) if the path doesn't exist or no artifact files are found. (An
  all-empty artifact set still yields a header-only blob — it does not raise, so
  the front-end must put real content in each file.)

**Implication:** name files with a numeric prefix (`01-…`, `02-…`) so the sorted
read gives a stable, logical order (intent → stories → units → testing posture).

## Required sections and their mapping to the AREA spec

The adapter hands the blob to an intake agent with one instruction: **carry EVERY
Unit of Work over as a feature, and EVERY Testing-Posture statement as an
acceptance criterion; invent no scope beyond the artifacts.** So the artifacts
must make those two things unambiguous.

| Inception artifact | Shape to follow | Becomes (AREA spec) |
|--------------------|-----------------|---------------------|
| **Intent / requirements** | the problem, goals, and any hard constraints | `spec.yaml` `summary` + framing (not scope by itself) |
| **Data model** (optional, in intent or its own file) | entities + fields | `spec.yaml` `entities[]` |
| **User stories** | `As a <role>, I want <capability>, so that <value>` — one per story, each with a stable id (`US-1`) | context for features (not 1:1) |
| **Units of Work (UoW)** | each a single buildable feature with a stable id (`UoW-1`) + a one-line description | `spec.yaml` `features[]` — **one feature per UoW** (`id` = kebab of the UoW) |
| **Testing Posture** | per UoW, one or more acceptance statements in **Given / When / Then** form | `acceptance.yaml` `criteria[]` — **one AC per statement**, `feature` = the UoW it tests |

Rules the front-end must honor so the translation is lossless:
1. **Every UoW has ≥1 Testing-Posture statement.** A UoW with no acceptance
   statement produces a feature with no criterion — AREA rejects that spec.
2. **Each Testing-Posture statement names its UoW** (e.g. "UoW-1:" prefix or a
   clear heading) so the AC can be tagged to the right feature.
3. **Given/When/Then is observable and testable** — it is the oracle seed; vague
   posture yields a weak oracle. Prefer concrete input→output examples.
4. **No scope outside the artifacts.** Anything not in a UoW will not be built.

## Recommended file set (the fixture's shape)

```
<inception-dir>/
  01-intent.md           # problem, goals, constraints, (optional) data model
  02-user-stories.md     # US-1, US-2, … (As a / I want / so that)
  03-units-of-work.md    # UoW-1, UoW-2, … (one buildable feature each)
  04-testing-posture.md  # per-UoW Given/When/Then acceptance statements
```

A single combined `inception.md` with those four sections is also valid (the
adapter blobs either way); separate numbered files are preferred for diff/review
and stable ordering.

## Evidence trail (round-trip)

Intake and later Construction events are appended to `aidlc_trace.jsonl` in the
spec dir, correlated by a `trace_id` (`new_trace_id()` / `emit_evidence()`), so
AI-DLC's own audit trail stays the system of record and AREA emits *into* it.
Front-end and pipeline phases share one `trace_id` end-to-end (Phase 3 widens the
events emitted: spec → locked oracle → gates → provenance → deploy).

## What is intentionally NOT in scope

AREA does **not** port AI-DLC's engine. The contract is the *file boundary* only;
any tool that writes compliant artifacts can drive AREA, and AREA's own Inception
engine (Phase 1) is just one such producer.
