"""Bước 2: spec artifact -> working Next.js app (light oracle).

Keyless: the agent scaffolds the app and writes Vitest tests that encode the
acceptance criteria at the logic level; the oracle runs a build + `vitest`.
run_until loops until both pass. Two targets:

- "plain"      -> vanilla Next.js, oracle = `next build` + vitest (Vercel-ready).
- "cloudflare" -> Cloudflare Workers via vinext (beta), oracle = `build:cf` + vitest.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml

from area.build.ui_vendor import VENDOR_DIR
from area.engine import (Backend, Verifier, VerifyResult, build_agent,
                         command_verifier, run_until)
from area.spec.models import Acceptance, Spec

# TDD preamble: an independent, locked acceptance suite already exists and IS
# the build oracle. Prepended to the build prompt when target is test-first.
_TDD_PREAMBLE = """\
=== TEST-DRIVEN DEVELOPMENT (read first) ===
Independent acceptance tests ALREADY EXIST and are LOCKED under __tests__/_holdout/
(see __tests__/_holdout/CONTRACT.md for the exact module paths + function
signatures they import). They were written by a separate verifier, not by you.
- Implement APP CODE so those locked tests pass. Honor the contract exactly
  (same import paths, same function names/signatures). Fixing/refactoring APP
  CODE is unrestricted — that is your job.
- You MUST NOT edit, rename, delete, or weaken any TEST under __tests__/_holdout/.
  The oracle rejects any run where a locked test changed.
- If (and only if) you are convinced a locked test is itself WRONG — it
  contradicts the spec or is impossible to satisfy — do NOT edit it. Instead
  write __tests__/_holdout/_CHALLENGE.md naming the exact test and why it is
  wrong, then keep fixing everything else. An INDEPENDENT verifier (not you)
  will adjudicate the challenge and, if valid, correct and re-lock that test.
- The oracle = production build is green AND `npx vitest run __tests__/_holdout`
  passes. Keep your OWN scratch tests elsewhere if you want; they are not the gate.

"""


# --- Oracles (guarded install + build + tests; exit 0 = pass) ---
_ORACLE_PLAIN = [
    "bash",
    "-lc",
    "[ -d node_modules ] || npm install --no-audit --no-fund; "
    "npm run build && npm test",
]
_ORACLE_CF = [
    "bash",
    "-lc",
    "[ -d node_modules ] || npm install --no-audit --no-fund; "
    "npm run build:cf && npm test",
]

_COMMON_RULES = """\
- Put the domain logic in a pure, importable module (e.g. lib/<entity>.ts) with
  one function per feature, so it is unit-testable WITHOUT a browser.
- Wire a minimal UI (app/page.tsx) to those functions using Server Actions.
- Use Vitest. Under __tests__/, write tests that assert EACH acceptance
  criterion (AC-*) at the logic/API level (no browser/E2E).
- PERSISTENCE: if the spec needs data to survive restarts, use a REAL durable
  store behind a small store INTERFACE (so the domain logic stays pure and the
  holdout tests run against an in-memory or sqlite test double — no external
  service at test time). plain target: node:sqlite (built-in) or better-sqlite3.
  cloudflare target: Cloudflare D1 (SQL) or KV. On cloudflare, keep any
  node:sqlite store TEST-ONLY so it never enters the build:cf Workers bundle.
- AUTH: if the spec needs sign-in, implement session-based auth with HASHED
  passwords, and keep auth + permission checks in a pure, testable module.
  Enforce per-user data isolation wherever the spec requires it.
- Add persistence / auth / external services ONLY when the spec calls for them;
  if the spec is a single-user in-memory tool, keep it that. Do not invent scope.
Keep it faithful to the spec.
"""


def _prompt_plain(spec_yaml: str, acc_yaml: str) -> str:
    return f"""You are the build stage of a software factory. Build a working \
Next.js app in the CURRENT WORKING DIRECTORY that implements this spec.

=== spec.yaml ===
{spec_yaml}
=== acceptance.yaml ===
{acc_yaml}

Requirements:
- Next.js (App Router) + TypeScript, using npm.
- package.json scripts MUST include exactly:
    "build": "next build"
    "test":  "vitest run"
- Make `npm install`, `npm run build`, and `npm test` all succeed. Run them
  yourself and fix until green.
{_COMMON_RULES}"""


def _prompt_cloudflare(spec_yaml: str, acc_yaml: str) -> str:
    return f"""You are the build stage of a software factory. Build a working \
Next.js app in the CURRENT WORKING DIRECTORY that implements this spec AND is \
deployable to Cloudflare Workers.

=== spec.yaml ===
{spec_yaml}
=== acceptance.yaml ===
{acc_yaml}

Cloudflare target (use Cloudflare's CURRENT recommended Next.js-on-Workers path):
- Use **vinext** (Cloudflare's recommended adapter, beta) + **@vinext/cloudflare**.
  Either scaffold with `npm create cloudflare@latest -- . --framework=next`
  (non-interactive; pass flags to avoid prompts) OR build a Next.js app and run
  `npx vinext init` (vinext needs Next.js 16 — upgrade Next if required).
- Keep Server Actions (they ARE supported on Workers via vinext).
- Enable `nodejs_compat` (compatibilityFlags: ["nodejs_compat"]).
- COMPAT-DATE GOTCHA (this breaks builds): vinext writes compatibility_date =
  TODAY, but the installed `workerd` can be a few days behind, and a future
  compatibility_date makes `build:cf` (vite build) FAIL. After init, run
  `npm ls workerd` and set compatibility_date (in cloudflare.config.ts / the
  wrangler config) to the installed workerd's release date OR EARLIER.
- Keep Vitest ISOLATED: its own vitest.config.ts with a plain node environment
  and NO vinext/Cloudflare plugins, so logic tests don't load the RSC/Cloudflare
  build pipeline. (vinext is Vite-based: build:cf = `vite build`, not next build.)

package.json scripts MUST include exactly these three (names matter — the
verifier calls build:cf and test):
    "test":     "vitest run"
    "build:cf": "<the vinext/Cloudflare Workers build command, e.g. build:vinext>"
    "deploy":   "<the Cloudflare deploy command, e.g. npx @vinext/cloudflare deploy>"

- Make `npm install`, `npm run build:cf`, and `npm test` all succeed (do NOT run
  deploy — that needs login). Run install/build:cf/test yourself and fix until green.
{_COMMON_RULES}"""


def _with_ui_parity(base: "Verifier", app: Path) -> "Verifier":  # noqa: D401
    """Add a UI term to what the build loop CONVERGES on.

    This is the gap that made a clone's look "always missing". Part A gave the builder
    the reference's real CSS/tokens/markup in `.area-ui/`, and part C could measure the
    result — but the oracle was still `npm install && build && test`, so the loop
    converged on BEHAVIOUR and the builder never received one signal about the look.
    Per AREA's own spine, quality is bounded by what the oracle contains, and the UI
    was not in it.

    Behaviour stays the hard requirement: a failing test is returned unchanged and the
    UI is not even measured. Only once the tests are green does the look get a say, and
    only against `visual.UI_ORACLE_FLOOR` — the "did you use the vendored reference at
    all" floor, not a fidelity demand. An UNMEASURABLE score never blocks: a thin SPA
    capture must not wedge a build.

    The shortfall comes back as actionable text (which colors/fonts are missing, where
    to read them), because a score alone is not something an agent can act on."""

    def _run() -> "VerifyResult":
        res = base()
        if not res.ok:
            return res  # behaviour first; it is the hard gate
        if app.parent.name != "apps":  # non-standard layout → measure() can't resolve
            return res
        try:
            from area.verify import visual

            m = visual.measure(app.name, root=app.parent.parent, pixel=False)
        except Exception as e:  # noqa: BLE001 — the look must not crash a green build
            print(f"[area] ui-parity: not measured ({type(e).__name__}: {e})")
            return res
        combined = m.get("combined")
        scores = m.get("scores") or {}
        if combined is None:
            why = "; ".join(f"{k}: {v}" for k, v in (m.get("skips") or {}).items())
            print(f"[area] ui-parity: not measurable — {why or 'no layer scored'} "
                  "(not blocking)")
            return res
        if combined >= visual.UI_ORACLE_FLOOR:
            print(f"[area] ui-parity: {combined:.2f} ≥ {visual.UI_ORACLE_FLOOR} "
                  f"(tokens {scores.get('tokens')}, dom {scores.get('dom')}) — the "
                  "vendored reference UI was used")
            return res
        return VerifyResult(ok=False, feedback=_ui_feedback(m))

    return _run


def _ui_feedback(m: dict[str, Any]) -> str:
    """What the builder must DO about a low parity score — not just the number."""
    from area.verify import visual

    scores = m.get("scores") or {}
    lines = [
        f"The app's acceptance tests pass, but it does NOT look like the reference it "
        f"is a clone of: visual parity {m.get('combined'):.2f} < "
        f"{visual.UI_ORACLE_FLOOR} (tokens {scores.get('tokens')}, "
        f"dom {scores.get('dom')}).",
        "",
        f"The reference's REAL UI is vendored at {VENDOR_DIR}/ — use it, do not "
        "re-invent a design:",
        f"  · {VENDOR_DIR}/tokens.json  — the reference's colors and fonts",
        f"  · {VENDOR_DIR}/styles/      — its actual stylesheets",
        f"  · {VENDOR_DIR}/rendered/    — its markup, to mirror the structure of",
    ]
    for key, vals in (m.get("missing_tokens") or {}).items():
        lines += ["", f"Reference {key} missing from your CSS: {', '.join(vals)}"]
    lines += ["",
              "Apply the reference's palette, fonts and layout structure to the pages "
              "you already built. Do NOT weaken or edit the acceptance tests."]
    return "\n".join(lines)


def build_app(
    spec: Spec,
    acc: Acceptance,
    app_dir: str | Path,
    *,
    target: str = "cloudflare",
    backend: Backend = "acp",
    model: Optional[str] = None,
    max_iters: int = 3,
    design: str = "",
    oracle: Optional[Verifier] = None,
    tdd: bool = False,
    ui_dir: Optional[str] = None,
) -> bool:
    """Scaffold + self-correct a Next.js app until the oracle passes.

    target="cloudflare" (default) builds a Workers-deployable app (vinext);
    target="plain" builds vanilla Next.js (`next build`).

    By default the oracle is `build + agent's own vitest`. In --tdd mode the
    caller passes `oracle=` (the locked holdout suite + build) and tdd=True, so
    the build loop is driven by an independent, unmodifiable test suite.
    """
    app = Path(app_dir)
    app.mkdir(parents=True, exist_ok=True)

    # exclude `ui`: it is a POINTER to vendored files (the real channel), not prose
    # for the prompt — dumping it would only bloat the build context.
    spec_yaml = yaml.safe_dump(spec.model_dump(exclude={"ui"}), sort_keys=False)
    acc_yaml = yaml.safe_dump(acc.model_dump(), sort_keys=False)

    if target == "cloudflare":
        prompt, oracle_cmd = _prompt_cloudflare(spec_yaml, acc_yaml), _ORACLE_CF
    elif target in ("plain", "vercel"):
        # vercel == vanilla Next.js (`next build`); deploy provider is Vercel.
        prompt, oracle_cmd = _prompt_plain(spec_yaml, acc_yaml), _ORACLE_PLAIN
    else:
        raise ValueError(
            f"unknown target: {target!r} (use 'cloudflare', 'vercel', or 'plain')"
        )

    # P6 memory: prepend known pitfalls; design stage (if any) as architecture.
    from area.memory import as_prompt, recall

    tags = ["build", target] + (
        ["cloudflare", "vinext"] if target == "cloudflare" else ["next"]
    )
    if design:
        prompt = f"=== Architecture (follow this design) ===\n{design}\n\n" + prompt
    if tdd:
        prompt = _TDD_PREAMBLE + prompt
    prompt = as_prompt(recall(tags=tags, text=spec_yaml)) + prompt

    # Ship AREA's skill pack into the app dir so the ACP Claude Code agent (cwd =
    # app dir) discovers them as project skills, and nudge it to use them.
    from area.skills import install_skills, skills_preamble

    installed = install_skills(app)
    if installed:
        prompt = skills_preamble(target) + prompt
        print(f"[area] skills: {', '.join('/' + n for n in installed)}")

    # Vendor the captured reference UI (Flow B parity) and nudge the builder to
    # reproduce it, so the clone matches the original's look instead of re-inventing.
    if ui_dir:
        from area.build.ui_vendor import install_ui_evidence, ui_preamble

        vendored = install_ui_evidence(app, ui_dir)
        if vendored:
            prompt = ui_preamble(vendored) + prompt
            print(f"[area] ui    : vendored reference UI ({', '.join(vendored)})")

    oracle = oracle or command_verifier(oracle_cmd, cwd=app)
    if ui_dir:
        oracle = _with_ui_parity(oracle, app)
    label = f"build:{target}" + (":tdd" if tdd else "")
    agent = build_agent(backend, model=model)
    try:
        passed, _ = run_until(
            agent, app, prompt, oracle, max_iters=max_iters, label=label
        )
    finally:
        agent.close()
    return passed
