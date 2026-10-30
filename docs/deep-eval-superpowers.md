# Deep evaluation — AREA (SW_Factory) × superpowers, feature by feature

Companion to [compare-superpowers.md](compare-superpowers.md). This is the granular pass:
every capability on both sides, with a **verdict per row** so we can (a) import superpowers'
good features, (b) keep AREA's moat, (c) delete AREA's dead weight / resolve its drift.

Grounded in: `obra/superpowers` v7.0.1 (15 skills + SessionStart hook) and AREA @ main
(29 CLI commands, ~26 `area/` modules, 11 `verify/` gates, 16 profiles, `area/engine` +
30M vendored OpenHands SDK, `area/web` dashboard).

### Verdict legend
- 🟢 **IMPORT** — bring the superpowers feature into AREA (AREA lacks it or is weaker)
- 🔵 **KEEP** — AREA wins decisively; keep as-is (superpowers has nothing / weaker)
- 🟣 **FUSE** — stack both (e.g. cheap gate in front of expensive gate)
- 🔴 **REMOVE / RESOLVE** — AREA dead weight, drift, or honesty gap to delete or fix
- ⚪ **N/A** — out of scope / not a goal

---

## A. Meta-discipline — how the agent and its *own* skills are governed

| # | Capability | superpowers | AREA | Verdict |
|---|---|---|---|---|
| A1 | Skill triggering / discovery | SessionStart hook force-injects "check skills first", survives compaction | PreToolUse `guard_holdout.py` *guards* but no discovery bootstrap | 🟢 IMPORT bootstrap |
| A2 | Skill-authoring discipline | `writing-skills`: TDD-for-docs, pressure-test vs fresh subagent, micro-test wording, "match form to failure" | none — profiles/skills hand-edited | 🟢 IMPORT |
| A3 | Grading the factory's own change | cheap behavioral micro-test (cents) | `evals.py` expensive matched-pair outcome (~$71, M9 priced-out) | 🟣 FUSE (cheap front, dear back) |
| A4 | Rationalization / red-flag wording | best-in-class tables ("violating the letter = violating the spirit") | thinner prose in 4 skills | 🟢 IMPORT wording craft |
| A5 | Instruction precedence (human > skill > default) | explicit | `CLAUDE.md` spine; Tung is top gate | 🔵 KEEP (both agree) |

## B. Spec / intake / design — the front end

| # | Capability | superpowers | AREA | Verdict |
|---|---|---|---|---|
| B1 | Requirement → validated spec | none | `spec/extract`,`spec/models`,`spec/clarify`,`adapt`,`research`,`intake/aidlc`,`web/intake`,`upload` | 🔵 KEEP (AREA rich) |
| B2 | Spec-vs-intent independent review | none | `spec/review` (anti blind-spot) | 🔵 KEEP |
| B3 | Pre-build brainstorm/design **hard gate** | `brainstorming`: locked design doc + **independent builder-check** subagent | `design.py` + docs 01/02 + ask-if-ambiguous, but no "can a blind builder plan from this alone?" check | 🟢 IMPORT builder-check |
| B4 | Spec-completeness before locking oracle | builder-check | `validate-spec.sh` (contract pre-flight) | 🟣 FUSE |

## C. Oracle / testing — the heart

| # | Capability | superpowers | AREA | Verdict |
|---|---|---|---|---|
| C1 | Test-authorship independence | **same agent** writes test + code | holdout authored by a **separate** subagent from spec only | 🔵 KEEP (AREA decisively) |
| C2 | Test immutability | prose "fix code, not test" | checksum lock + `verify-holdout-intact.sh` + PreToolUse editor block | 🔵 KEEP |
| C3 | Watch-it-fail (RED) is mandatory | Iron Law, explicit | implicit ("build to green") | 🟢 IMPORT RED-verify for AREA's own engine tests |
| C4 | Adversarial / failure-mode coverage | `writing-plans` **"Review Focus"**: force a test per spec-implied input no AC covers | `verify/chaos` + holdout "cover every AC" (AC happy-path-biased) | 🟢 IMPORT Review Focus into `holdout-author` |
| C5 | Clone / behavioral-parity oracle | none | `re/extract`,`re/ui_capture`,`verify/visual`,`build/ui_vendor` | 🔵 KEEP |
| C6 | Test-strength meta-gate | none | `verify/strength` — "can this test settle its claim?" | 🔵 KEEP (unique) |

## D. Build loop / execution

| # | Capability | superpowers | AREA | Verdict |
|---|---|---|---|---|
| D1 | Execution model | subagent-driven OR inline, per-task review | `pipeline` Flow A/B + self-correct loop + `engine/adapter` | 🔵 KEEP core |
| D2 | Root-cause-before-fix + **anti-symptom-patch** | `systematic-debugging` Iron Law | — AREA's **#1 documented bug class** is symptom-patching a gate to green | 🟢 IMPORT (highest value) |
| D3 | N-failed-fixes circuit breaker | **3 strikes → stop, question architecture** | weaker ("same failure twice") | 🟢 IMPORT / strengthen |
| D4 | Compaction-proof resume ledger | `executing-plans` `progress.md` | none — loops capture oracle at import (*stale-oracle-mid-loop* bug) | 🟢 IMPORT |
| D5 | Experience memory (pitfalls → prompts) | none | `memory/store` | 🔵 KEEP (unique) |

## E. Verification gates

| # | Capability | superpowers | AREA | Verdict |
|---|---|---|---|---|
| E1 | Deterministic security audit | none | `verify/audit` (two-tier) | 🔵 KEEP |
| E2 | NFR / perf budget | none | `verify/nfr`,`verify/perf` | 🔵 KEEP |
| E3 | Chaos / resilience | none | `verify/chaos` | 🔵 KEEP |
| E4 | Live E2E (auth/forms) | none | `verify/e2e` (Playwright) | 🔵 KEEP |
| E5 | Visual parity | none | `verify/visual` | 🔵 KEEP |
| E6 | Product-fit | none | `verify/product`,`reality.py` | 🔵 KEEP |
| E7 | Cost cap | none (no cost model) | `verify/cost` (post-hoc; Group 3 adds pre-emptive) | 🔵 KEEP |
| E8 | Claim → **fresh evidence** before "done" | `verification-before-completion` Iron Law | gates deterministic but *BLOCK-but-PASS* leakage; `verify/_runners` asserts tests ran (partial) | 🟣 FUSE |

## F. Independence / review — separation of duties

| # | Capability | superpowers | AREA | Verdict |
|---|---|---|---|---|
| F1 | Reviewer **blind** to builder's reasoning | `requesting-code-review`: reviewer gets only {desc + reqs + SHA}, never session history | profiles separate kinds; review stage mostly deterministic | 🟢 IMPORT the blind-judge rule for any LLM-review |
| F2 | Implementer can't grade self / controller can't pre-judge reviewer | `subagent-driven-development`, explicit ("prompt says 'do not flag' → stop") | spine *implies* it, not stated as a rule | 🟢 IMPORT as explicit profile rule |
| F3 | Model-tiering (cheap builder, capable judge) | explicit | profiles carry a model per kind | 🟣 FUSE (make "judge ≥ builder" explicit) |

## G. Isolation / hygiene

| # | Capability | superpowers | AREA | Verdict |
|---|---|---|---|---|
| G1 | Per-build isolated, **verified-ignored** sandbox + green baseline | `using-git-worktrees` | shared `workspace/apps/` dir (*holdout shared-dir race*) | 🟢 IMPORT (Group 3) |
| G2 | Input credential screening | none | `screen.py` ("keep creds out of what the agent reads") | 🔵 KEEP (unique) |
| G3 | Factory self-integrity (tamper-check own code mid-run) | none | `verify-factory-intact.sh` | 🔵 KEEP |

## H. Provenance / supply-chain — AREA's moat

| # | Capability | superpowers | AREA | Verdict |
|---|---|---|---|---|
| H1 | Build provenance (spec digest → gates → artifact sha) | none | `provenance.py` (SLSA-style), `evidence.py` | 🔵 KEEP (moat) |
| H2 | Fail-closed deploy on provenance mismatch | none | deploy verifies provenance | 🔵 KEEP |
| H3 | CVE / supply-chain gate | none | `vinext-cf-build` skill + `verify/audit` (braces) | 🔵 KEEP |

## I. Finish / deploy / monitor

| # | Capability | superpowers | AREA | Verdict |
|---|---|---|---|---|
| I1 | Human-gated integration + typed `discard` token | `finishing-a-development-branch` | `export`,`rollback`,`deploy --dry-run`; no explicit integrate-menu | 🟢 IMPORT menu + typed-confirm |
| I2 | Re-verify on the **exact** merged/deployed artifact | re-run suite on merged tree | provenance checks artifact sha (stronger) | 🟣 FUSE (provenance + re-run) |
| I3 | Deploy to own infra (CF / Vercel) | none | `deploy/cloudflare`,`deploy/vercel` | 🔵 KEEP |
| I4 | Prod monitoring + spec-level self-heal | none | `monitor.py`,`heal.py` | 🔵 KEEP (unique) |

## J. Observability / failure analysis

| # | Capability | superpowers | AREA | Verdict |
|---|---|---|---|---|
| J1 | Cost / latency / outcome per run | none | `obs.py`,`trace.py` (Langfuse) | 🔵 KEEP |
| J2 | **Citation-grounded** post-mortem ("no path:line, no finding") + independent analysts | `diagnosing-superpowers` | self-audit docs are self-asserted prose | 🟢 IMPORT methodology |
| J3 | Feature map of built app | none | `feature_map.py` | 🔵 KEEP |

## K. Breadth / distribution / portability

| # | Capability | superpowers | AREA | Verdict |
|---|---|---|---|---|
| K1 | Works on existing large codebases | yes | greenfield-only | 🟢 IMPORT breadth skills for non-factory work |
| K2 | Multi-harness portability | Muse/Pi/Hermes/Antigravity/Codex/Copilot | Claude Code only | ⚪ low priority |
| K3 | Distribution / ecosystem | 2-cmd install, huge | bespoke single-user | ⚪ N/A (not a goal) |

## L. Dead weight / drift — AREA weaknesses to remove or resolve

| # | Finding | Evidence | Verdict |
|---|---|---|---|
| L1 | **The programmatic OpenHands engine vs the "native" thesis** | `area/engine/adapter.py` wraps the **30M** vendored OpenHands SDK; **both** `--backend acp` (drives Claude Code CLI via ACP) **and** `--backend llm` (OpenHands+LiteLLM) run through it; default is `acp`. The real "native" path (the skills + `tools/*.sh`, driven by Claude Code directly) **bypasses the engine entirely** — yet `CLAUDE.md:103-105` claims main has "no ACP wrapper". | 🔴 **LIVE — decided 2026-10-30: native is the intent → retire the programmatic engine from main.** Scope (verified): a **clean seam** exists — 6 modules import only helpers (`scrubbed_env`, `Backend` type → extract to a leaf, drop OpenHands transitively); ~16 modules genuinely drive an agent (`build_agent/run_until/run_once/ask_cli/command_verifier`, incl. the author/fix phases of audit·chaos·e2e·holdout·product). Those either move to `saas-coordinator-runner` (its stated home) or get re-pointed to a native executor. **A real project — needs its own staged plan + branch, not a default-flip.** |
| L2 | `area runner` documented but absent | `docs/RUNNER.md` + `Dockerfile.runner` describe `area runner` (not in CLI; `scripts/run-runner.sh` absent) | ✅ **ALREADY DONE** (verified 2026-10-30): both files carry a prominent "not on `main` / saas-branch" banner; remaining `area runner` refs are legit (ADR 0002 design, self-audit M5). No action. |
| L3 | Stray wrangler cache | `coordinator-cf/.wrangler/cache/wrangler-account.json` | ✅ **ALREADY CLEAN** (verified 2026-10-30): `coordinator-cf/` is **not git-tracked** and `.wrangler` is gitignored (`.gitignore:34-35`). My first-pass "committed" claim was wrong. No action. |
| L4 | `area/web` dashboard vs "no dashboard on main" claim | `area/web/{server,jobs,auth,chat,intake,upload}` on main; `CLAUDE.md:103` lists "web dashboard" as a saas-branch thing | 🔴 **LIVE** — same drift shape as L1; resolve together. |
| L5 | Stale self-records (mypy "phased subset", stale test counts) | — | ✅ **ALREADY DONE** (verified 2026-10-30): `CONTRIBUTING.md` deliberately quotes no test count ("`make test` prints the real one") and states mypy `strict` over the **whole** `area` package; no `343`/`347` found repo-wide. No action. |

> **Note on this table's own accuracy:** L2/L3/L5 were drawn from a **stale** plan file
> (`.claude/plans/tranquil-hugging-quail.md`) + a first-pass read; verification against
> current `main` shows they already landed. Only **L1** and **L4** are live — and L1's
> direction is now decided (retire ACP). *Finding things by running, not reading, cuts both
> ways: it also catches stale "weaknesses" that were already fixed.*

---

## Summary — what to do with the deep pass

**Import from superpowers (🟢, ranked by value):**
1. `systematic-debugging` → root-cause + 3-strike circuit breaker + **anti-symptom-patch** (D2, D3) — kills AREA's #1 bug class.
2. `writing-plans` "Review Focus" (C4) — widen the oracle past happy-path.
3. `writing-skills` discipline (A2) + micro-test as the cheap front gate to `evals.py` (A3) — unblocks M9.
4. SessionStart bootstrap (A1) — make AREA's own skills fire.
5. `brainstorming` builder-check (B3), worktree isolation (G1), resume ledger (D4), blind-reviewer rules (F1/F2), finish-menu (I1), citation post-mortems (J2).

**Keep (🔵) — AREA's moat, superpowers has nothing:** the independent locked oracle (C1/C2),
all deterministic gates (E1–E8), provenance/supply-chain (H1–H3), clone/visual parity (C5),
spec pipeline (B1/B2), monitor+heal (I4), obs (J1), screen + factory-integrity (G2/G3),
test-strength and feature-map (C6/J3).

**Remove / resolve (🔴):** only **L1** (ACP-vs-native drift + 30M SDK — decided: retire ACP)
and **L4** (dashboard, same shape) are live. L2/L3/L5 were already fixed on `main`.

**Order:** L1 is the real remaining red but a 25-importer surgery → it gets its own plan +
branch (investigate the native path's completeness first). The Tier-0 🟢 imports (D2/D3, C4,
E8) are independent of L1, cheap, and each targets a documented defect — do them in parallel.
Everything imported must itself pass the A2 `writing-skills` test, so the merge runs under the
discipline it installs.
