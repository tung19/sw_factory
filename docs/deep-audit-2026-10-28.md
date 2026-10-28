# Deep audit — 2026-10-28 (comprehensive)

Four independent audit passes over `area/` (gates/oracle · pipelines/CLI/engine ·
security surfaces · spec/RE/evals/build), each finding verified by **running or by
decisive code-reading**, not relayed on trust. Baseline at audit time: `main` @
`4f96a8a7`, ruff clean, mypy strict (68 files), pytest **951 passed**.

**Meta-finding:** none of the defects below are caught by the current gates — they are
logic/semantic/security gaps that a green suite does not see. This is the recurring lesson
of this repo (*found by running, not by a green check*) applied to the factory itself.

## Bug list

| ID | Area | Sev | Defect | Root cause | Fix |
|----|------|-----|--------|-----------|-----|
| **B1** | `pipeline.py:233/364/459` | **HIGH** | `--use-spec` skips re-extraction but the independent spec **reviewer still runs**; it mutates `assumptions.yaml` (∈ `spec_digest`, which the clarify confirmation is anchored on), so a confirmed spec rebuilt with `--use-spec --spec-review` (default on) can get its confirmation voided and the clarify gate **re-walls** the operator. Intermittent (LLM reviewer is non-deterministic: documented 8→2→11). | capability not threaded to one stage (C3) — reuse propagated to the extractor but not the reviewer; the reviewer's write target is digest-covered | gate the reviewer on `not use_spec` in all three pipelines (smallest, matches intent) |
| **B2** | `screen.py:57-63` | **HIGH** | Secret-value charclass `[A-Za-z0-9/+_.=~-]{16,}` excludes most punctuation, yet keys target `password`. `DB_PASS = "Str0ng!P@ss#2024"` → **0 findings, not redacted** (ran). The password reaches the build agent. | matcher narrower than what it guards (C1) | widen the value class / match a quoted value `"[^"\n]{8,}"` when a quote was captured |
| **B3** | `screen.py:117-120,168-182` | **HIGH** | `_EXCLUDE_VALUE` is a case-insensitive **substring** test on the matched value, so any real secret *containing* `sample/todo/placeholder/…` is treated as a placeholder. `ghp_sample…` and `postgres://u:Todo1234pass@h` → **0 findings** (ran). | a guard disables another guard (C1/guard-vs-guard) | anchor the placeholder test to the **whole** value (equality/`fullmatch`), not a substring |
| **B4** | `pipeline.py:424 vs 438` | **MED** | In `clone_pipeline` the RE agent runs **first** and is told to read `_sample/` directly; `screen.scan_tree` + its report run **after**. A credential in the reference reaches the RE agent before the screen prints — the exact PocketOS shape the screen exists to stop. Only the downstream build copies are redacted. | wrong order of a guard vs the consumer (C3) | run `scan_tree` **before** `spec_from_source`; feed the RE agent a redacted view, keep byte-exact `_sample/` for provenance only |
| **B5** | `obs.py:88-118` | **MED** | `installed_skills` memoizes per app name with no invalidation; the pre-build **spec** stage calls it before `.claude/skills/` exists, caching `(None,())`, so every later build-stage run on a **fresh** app records `skills: [], skills_digest: null` (ran: still `(None,())` after the dir is created). `area evals` then pairs runs as if the skill pack were absent — undermining the evals baseline (F4). | memoizing a value that changes during the process (C3) | only memoize a **positive** result; or key on dir mtime/existence; or drop the memo |
| **B6** | `deploy/vercel.py:226` | **MED** | `provision_postgres` returns `True` on **every** path incl. a migration that failed (`applied N/len` logged, still `True`). `deploy/__init__.py:_provision` blocks only on `False`, so for Vercel the block is **unreachable** → a production deploy proceeds with an unmigrated/absent DB. Asymmetric with `cloudflare.provision_d1` (returns `ok_all`). | fail-open (C2); also a docstring contradicts the deploy posture | return `False` on a connected store's migration failure (mirror `provision_d1`); decide deliberately on "store not connected" — **needs Tung to adjudicate the contract** |
| **B7** | `engine/adapter.py:311-319,425-435` | **MED** | A profile's `budget_usd`/`agent_iters` is applied **before** `_mk_conversation` reads the env var that carries the CLI `--budget`/`--agent-iters`, so a profile value **shadows the CLI flag** — inverting the documented "a CLI flag always wins" and silently weakening a cost cap. Latent (profiles ship `null`). | precedence inversion (C3) | read the CLI-flag env **before** the profile default, or thread `--budget` as an explicit kwarg |
| **B8** | `verify/holdout.py:170,185` | **MED** | `_has_tests`/`_test_text` use a narrower extension set (`.ts/.js…`) than the runner (`_runners.py` incl. `.mjs/.mts/.cjs/.cts`) and the AC-counter. A `.mjs`-only holdout → `_has_tests` **False** (ran) → `author_until` raises "holdout authoring failed": a valid, lockable oracle is rejected and the build cannot complete. | matcher narrower than what it guards (C1) | one shared `_TEST_EXTS` (match `_runners`) used by `_has_tests`, `_test_text`, `_expected_ac_count` |
| **B9** | `engine/adapter.py:487` + `provenance.py:83` | **MED** | `.area-lesson.md` is deleted only inside `_harvest_lesson`, called only when `passed and used>1 and first_fail`. A **failed** build (or a first-try-green rebuild) leaves it; `.md` is not in provenance `_SKIP_*`, so `artifact_digest` hashes it — contradicting the docstring's "never reaches the artifact digest". | invariant enforced at the wrong place (C4) | unlink the lesson file unconditionally at the end of `run_until`, or add `.area-lesson.md` to `_SKIP_FILES` |
| **B10** | `provenance.py:223` | LOW-MED | `_oracle_strength` globs `*.ts` **non-recursively** → a `.tsx/.jsx/.mjs` or nested holdout yields empty text → every criterion reads UNCOVERED → the attestation records the oracle as **clean** when it wasn't measured. The field exists precisely to flag a decorative oracle (the `expenses` AC-14 case). | narrow glob (C1), records a property it didn't measure | `rglob("*")` filtered by the shared `_TEST_EXTS` |
| **B11** | `cli.py:405 vs 580` | LOW-MED | `area iterate --audit` enforces at level **"high"** (gate's `getattr` default) but provenance records `auditLevel: null` (iterate subparser lacks `--audit-level`) → the attestation under-reports the threshold it enforced (ran: iterate→`null`, run→`'high'`). | capability gap on one of four pipelines (C3) | add `--audit-level` (+ `--nfr-build/--visual`) to iterate, or record the effective default |
| **B12** | `obs.py:111` | LOW-MED | Per-run `skills_digest` hashes only each skill's `SKILL.md`, while `profile._pack_digest` hashes the full subtree. Two packs differing in `references/*`/vendored scripts collide → the evals `confounded-skills` guard is **blind** to intra-skill changes. | narrower hash than the thing it guards (C1) | hash the full skill subtree (`sorted(rglob)`) like `_pack_digest` |
| **B13** | `verify/nfr.py:186` | LOW | `if not results: return True` ignores `blocking` (perf.py fixed the same shape) → under `--strict` with no `nfr.yaml` and zero measurable metrics, the gate passes by absence. Edge (a normal app yields `_dep_count`). | fail-open (C2) | mirror perf: `if not results: return False` when `blocking` |
| **B14** | `screen.py:38` | LOW | Files > `MAX_SCAN_BYTES` (2 MB) are copied verbatim, only flagged. Minified bundles — the stated input — routinely exceed 2 MB, so a secret in one passes. Documented, reported loudly. | threshold low for the intended input (tradeoff) | stream-scan large text in overlapping chunks |
| **B15** | `seed.py:18-22,81-88` | LOW | PII strip is exact lowercased field-name match → `email_address`, `phoneNumber`, `firstName`, `billing_address` leak. Opt-in + best-effort, hence low. | matcher too exact (C1) | normalized/substring token match (name/email/phone/address/ssn/card) |
| **B16** | `evals.py:388` | LOW | `record_experience` calls `compare` with **no** `only_tasks`, while the gate `check()` restricts to declared `evals/tasks.yaml` → a lesson can be recorded on a broader/decisive verdict the gate itself wouldn't reach. | two callers of one fn disagree on scope | pass `only_tasks=load_task_set()` in `record_experience` |
| **B17** | `spec/models.py:162` | LOW · **DORMANT** | `routes_unquoted` uses `if not any(pp in text …)`; a declared `"/"` route matches any text with a slash, so a criterion navigating to an **undeclared** path isn't flagged. Dormant — only called when `spec.routes` is empty. | substring match where segment match is needed (C1) | word-boundary / path-segment match; harden before activating |
| **B18** | `re/ui_capture.py:278` | LOW · note | `_capture_from_sample` iterates unsorted then truncates at 60 files → which subset lands in `_ui/` is filesystem-order dependent (non-reproducible). Not a digest input. | unsorted before a cap | sort before the cap (`ui_vendor.py` already does) |

## Root-cause clusters (the "đánh giá")

- **C1 — a check reads a narrower surface than the thing it guards** (B2, B3, B8, B10, B12, B15, B17). The repeatable cure is *one shared definition* (ext set / value charclass / full-subtree hash / segment match), not seven ad-hoc ones. This is the dominant cluster.
- **C2 — absence read as pass (fail-open)** (B6, B13). A step returns OK when it could not measure/provision.
- **C3 — a capability/stage threaded or ordered wrong** (B1, B4, B5, B7, B11). Same family as the `iterate` bug fixed in #60: a flag/step honored on some paths/stages but not all. B4 and B1 are *order/stage* variants; B7 a precedence inversion; B5 a lifetime-of-memo variant.
- **C4 — an invariant enforced in the wrong place** (B9): the "always deleted" promise lives inside a conditionally-called function.

## Suggested fix order

1. **B1** — it re-walls an operator who did everything right (highest user-facing impact).
2. **B2 + B3** — the credential screen's core job fails in the normal flow; one-line repros. Fix together with B4 (the screen also runs too late for the RE agent).
3. **B5** — unblocks a trustworthy evals baseline (the F4 work depends on it).
4. **B6** (after Tung adjudicates the Vercel contract), **B7**, **B8**, **B9**.
5. The C1 extension/hash cluster (B8/B10/B12) is cheap to fix as one shared constant.
6. Remainder (B11–B18) as cleanup.

## Checked and clean (no action)

`_safe_clone_source` (rejects `ext::`/`fd::`/option-injection, allows normal URLs) ·
`web/auth.py` (constant-time token, `?token=` 303-handoff, HttpOnly/SameSite, no
auth-skip) · `deploy_with_gate` provenance (fail-closed: mismatch/absent/stale/unknown all
refuse; checker-exception refuses; `_settle_before_attesting`) · `provision_d1` (migration
filename `shlex.quote`d) · `jobs.cancel` (process-group kill) · `isolate_local_path`
(skips symlinks, contained) · audit/perf/cost/visual/strength verdict logic · profile_digest
coverage · `memory.remember` (both halves; redact-after-deforge order correct) ·
env-scrub scope around the build pipelines · in-slice subprocess timeouts.

## Status (updated after remediation)

All MED-and-up findings fixed and merged. Remaining is one deferred item and one residual.

| Finding | Status |
|---|---|
| B1, B2, B3, B5 | ✅ merged (#62, #63, #64) |
| B7, B8, B9, B10, B12 | ✅ merged (#65, #66, #67, #68) |
| B6, B4 | ✅ merged (#69, #70) — B4 **local-path** scope |
| B11, B13, B15, B16, B17, B18 | ✅ this cleanup PR |
| **B14** | ⏸ deferred — screen's 2 MB cap needs a chunked scanner (documented tradeoff, reported loudly) |
| **B4 git/URL** | ⏸ residual — closing non-local references needs the pipeline to fetch before the RE agent + a funded live clone run to confirm the agent honours the redacted-view prompt |
