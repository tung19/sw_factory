# `area adapt` — research-augmented clone & adapt (Flow B+)

**Status:** spec confirmed (Tung, 2026-10-22); **all phases P0–P4 + the capstone
SHIPPED** (logic agent-free-tested; live LLM/web dogfood of the research +
end-to-end build deferred until funded). This is a new AREA capability, not a
generated app — the oracle here is AREA's own test suite. Command: `area adapt
<reference> "<requirement>"` (research → requirement-anchored synthesis → one-shot
clarify → spec written → `area intake` build handoff; `--seed`/`--seed-attest` for
opt-in reference seeding).

## 1 · Engineering intent (why)
Flow B (`area clone`) reverse-engineers ONE reference to build-to-parity; Flow A
(`area run`) builds from a requirement. Neither (a) surveys the ecosystem to borrow
proven structure/features, (b) treats the reference as a *starting point to adapt*
where the user's requirement wins on conflict, nor (c) auto-fills an unclear
requirement from research and confirms once. `area adapt` fills those gaps, with a
**data dimension** (persistence + ingest/ETL + optional seed-from-reference) as a
first-class concern.

## 2 · Confirmed decisions
- **(1) Cost/determinism:** the research stage is LLM + web heavy and
  non-deterministic. Controls = the one-shot **clarify confirm** + **`--budget`** cap.
- **(2) Security/legal (synthesized):**
  - *Analyzing untrusted repos/web:* clone shallow (`--depth 1`) into a throwaway
    scratch dir (never near secrets), **read statically — never install/build/run**
    the researched repos, reuse `_safe_clone_source` (blocks `ext::`/`fd::` RCE),
    treat all research output as **data, not instructions**, and **scrub cloud/deploy
    secrets from the agent env** while it reads untrusted content (= P0 / audit #10),
    destroy the scratch clones after.
  - *Seed-from-reference data:* **opt-in, behind an explicit user authorization
    attestation.** When on: honor robots.txt + crawl-delay, **public data only (no
    auth bypass)**, rate-limit, clear user-agent, prefer an official API, **skip PII
    by default**, bounded sample, record provenance. AREA surfaces the checklist +
    requires the attestation — it does not itself rule on legality (human is the top
    gate).
- **(3) Phasing:** P0 → P4 below (P0 added because the research stage reads the most
  untrusted content, so secret-scoping must come first).
- **(4) Build posture:** build + unit-test each phase **agent-free** (like the
  gates); defer live LLM/web dogfood until Tung funds a run.

## 3 · Product requirements
- **PR-1** Input: a reference (git URL / repo / live URL / path) + a requirement
  (may be partial/unclear).
- **PR-2** Reference RE: reuse `spec_from_source` → the reference's features + data model.
- **PR-3** Research (LLM + web): discover ~100 comparable repos → rank by quality
  signals → select top-5 → analyze each for `{features, data_source,
  data_integration, data_storage}` → a structured **research brief**.
- **PR-4** Spec synthesis: merge **requirement (AUTHORITATIVE — wins on conflict)** +
  reference RE + research brief → a draft spec + AC, each AC tagged with its
  **source** (requirement / reference / research).
- **PR-5** Unclear→confirm: where the requirement is silent, research auto-fills a
  proposed decision; the **clarify gate STOPS once** with the filled spec (sources
  shown); build proceeds only on confirm.
- **PR-6** Data dimension in the built app: (a) provision DB + schema, (b) an
  ingest/ETL feature per the synthesized data requirements, (c) **opt-in**
  seed-from-reference (attested, with the §2 safeguards).
- **PR-7** Build: oracle-loop — lock an independent holdout from the **confirmed**
  acceptance (requirement wins) → build-to-green → gates.
- **PR-8** Provenance: record the research brief, the chosen repos, and each AC's
  source in the evidence trail.

## 4 · Acceptance criteria (feature-level)
- **AC-1** reference + requirement → a research brief listing ≥5 analyzed repos,
  each with `{features, data_source, data_integration, data_storage}`.
- **AC-2** on a requirement⟂reference/research conflict, the synthesized spec follows
  the **requirement** (verified on a crafted conflict fixture).
- **AC-3** an unclear requirement → the clarify gate STOPS exactly once with a filled
  spec showing each decision's source; build only after confirm.
- **AC-4** the synthesized `acceptance.yaml` is well-formed and every AC is traceable
  to a source.
- **AC-5** the built app persists durably (DB + schema) AND exposes the spec's
  ingest/ETL feature.
- **AC-6** (opt-in, default OFF) seed-from-reference imports N records visible in the
  built app, only after the authorization attestation.
- **AC-7** research + build cost is bounded by `--budget` and recorded in obs/evidence.
- **AC-8** (P0, security) while the agent processes untrusted content, deploy/cloud
  secrets are absent from its environment and restored afterwards.

## 5 · Phases (each = 1 PR, logic-first agent-free, live-dogfood deferred)
- **P0 — secret-scoping prereq (audit #10):** scrub cloud/deploy secrets from the
  agent env around every agent run (`area/engine/adapter.py:_scrubbed_agent_env`).
  **← this PR.** Covers AC-8.
- **P1 — research stage** (`area/research/`): the discover→rank→top-5→analyze
  pipeline + the research-brief schema. Orchestration/parse/rank testable agent-free.
- **P2 — synthesis + clarify:** requirement-anchored merge + per-AC source + the
  one-shot clarify gate.
- **P3 — data dimension:** persistence + ingest/ETL feature generation.
- **P4 — seed-from-reference:** opt-in, attestation + robots.txt/public-only/
  rate-limit/no-PII/provenance safeguards. ✅ (`area/seed.py`)
- **Capstone — `area adapt` pipeline** ✅ (`area/adapt.py:adapt_pipeline` + CLI):
  composes research → synthesis → data plan → one-shot clarify → writes
  spec+acceptance → `area intake` build handoff → opt-in seed. Agent steps injected
  (`researcher` / `reference_features`) for agent-free tests.

**Shipped:** P0 `#20` · P1 `#21` · P2 `#22` · P3 `#23` · P4 `#24` · capstone (this).

## 6 · Deferred / out of scope (noted)
Live LLM/web dogfood of the research stage (needs a funded run); the actual
~100-repo discovery is agent-driven and non-deterministic — its quality is gated by
the clarify confirm, not asserted by a unit test.
