"""Bước 2: spec artifact -> working Next.js app (light oracle).

Keyless: the agent scaffolds the app and writes Vitest tests that encode the
acceptance criteria at the logic level; the oracle runs a build + `vitest`.
run_until loops until both pass. Two targets:

- "plain"      -> vanilla Next.js, oracle = `next build` + vitest (Vercel-ready).
- "cloudflare" -> Cloudflare Workers via vinext (beta), oracle = `build:cf` + vitest.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from area.engine import build_agent, command_verifier, run_until
from area.spec.models import Acceptance, Spec

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
- A simple in-memory store is fine (no external services, no auth, single user).
Keep it minimal and faithful to the spec. Do not invent scope.
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


def build_app(
    spec: Spec,
    acc: Acceptance,
    app_dir: str | Path,
    *,
    target: str = "cloudflare",
    backend: str = "acp",
    model: Optional[str] = None,
    max_iters: int = 3,
) -> bool:
    """Scaffold + self-correct a Next.js app until build + Vitest pass.

    target="cloudflare" (default) builds a Workers-deployable app (vinext);
    target="plain" builds vanilla Next.js (`next build`).
    """
    app = Path(app_dir)
    app.mkdir(parents=True, exist_ok=True)

    spec_yaml = yaml.safe_dump(spec.model_dump(), sort_keys=False)
    acc_yaml = yaml.safe_dump(acc.model_dump(), sort_keys=False)

    if target == "cloudflare":
        prompt, oracle_cmd = _prompt_cloudflare(spec_yaml, acc_yaml), _ORACLE_CF
    elif target == "plain":
        prompt, oracle_cmd = _prompt_plain(spec_yaml, acc_yaml), _ORACLE_PLAIN
    else:
        raise ValueError(f"unknown target: {target!r} (use 'cloudflare' or 'plain')")

    oracle = command_verifier(oracle_cmd, cwd=app)
    agent = build_agent(backend, model=model)
    try:
        passed, _ = run_until(agent, app, prompt, oracle, max_iters=max_iters)
    finally:
        agent.close()
    return passed
