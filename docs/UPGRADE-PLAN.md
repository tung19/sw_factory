# AREA — Upgrade plan (toward 10/10)

An external review scored the repo **7.5/10** overall (≈8.5 architecture/docs,
≈5.5 usability/production-ready). That review read the surface; from inside the
codebase the diagnosis sharpens:

> **The capability is strong; the value is invisible.** Generated apps are
> gitignored, so a visitor sees a *framework*, not a *product that runs* — and
> seeing it work at all needs a Claude key + ~$ + ~10 min. The gap to 10/10 is
> **packaging + visible evidence**, not "more AI".

What the review missed (already in the repo): CI + **343 tests**, an
independently-audited + hardened security/gate layer (holdout-must-run, provenance
blocks deploy, clone-RCE guard, …), `docs/ARCHITECTURE.md` + `CONTRIBUTING.md`, 2
ADRs, `scripts/install.sh` + `area doctor`.

## The crux
Make the value **appear in 3 minutes, without an LLM key** — a committed, runnable
example with its spec + locked oracle + gate evidence, plus a keyless `area demo`.

## Waves

### Wave 1 — make the value visible (autonomous, no token) ⭐ highest ROI
1. **`examples/`** — one real app the factory built, committed with its **source +
   spec + locked holdout + evidence** (gate results, provenance, audit trail), no
   `node_modules`. A visitor sees *what the factory produces* and the oracle-loop
   proof.
2. **`area demo` (keyless)** — run a pre-built example app locally (install → build
   → serve → open browser) with **no Claude key and no cost**, so the product can
   be *seen working* in minutes.
3. **Lint + type-check in CI** — add `ruff` (fast, high-value) and phase in `mypy`.
4. **Governance scaffolding** — `SECURITY.md` (the model + this repo's audit),
   `CODEOWNERS`, issue/PR templates, an ADR for the oracle-loop.

### Wave 2 — setup, UX, golden path (mostly autonomous)
5. **1-command bootstrap** — `make setup` wrapping `install.sh` + `doctor` + `demo`.
6. **Product-first README** — lead with "what you do in the first 3 minutes" + a
   golden-path diagram + a link to the example evidence (philosophy moves lower).
7. **One golden path** — all docs/scripts point at a single
   `requirement → spec → oracle → build → gates → deploy` pipeline; the other
   flows (clone, intake, inception, the saas branch) are labeled *advanced/optional*.
8. **CLI UX** — clearer `--help`, clearer errors, an `area quickstart`; split the
   640-line `cli.main` dispatch (audit finding F7).

### Wave 3 — case study + maturity (some needs the owner)
9. **`docs/CASE-STUDY.md`** — the full story of one build (requirement → spec →
   locked oracle → 7 gates → trace → evidence) with screenshots.
10. **A live-deployed demo** (needs a deploy token) — a public URL is the strongest
    evidence.
11. Release strategy + `CHANGELOG.md` + versioning + deprecation policy.

## Scoring target
- Architecture / discipline / security: already ~8.5.
- Usability / production-ready: ~6 now → **8.5–9 after Waves 1–2 (no token needed)**;
  reaching 10 needs the live demo + case study (Wave 3).

## Status
- [x] W1.1 examples/ (`examples/taskboard` — source + spec + locked oracle + evidence)
- [x] W1.2 `area demo <name>` (keyless: install → build → serve → open)
- [x] W1.3 CI lint (ruff F,E9 in CI; cleaned 12 unused-import/var findings)
- [x] W1.4 governance (SECURITY.md, CODEOWNERS, issue/PR templates, ADR-0003 oracle-loop)
- [ ] W2.5 bootstrap · [ ] W2.6 README · [ ] W2.7 golden path · [ ] W2.8 CLI UX
- [ ] W3.9 case study · [ ] W3.10 live demo · [ ] W3.11 releases
