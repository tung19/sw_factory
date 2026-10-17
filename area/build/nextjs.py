"""Bước 2: spec artifact -> working Next.js app (light oracle).

Keyless: the agent scaffolds the app and writes Vitest tests that encode the
acceptance criteria at the logic level; the oracle runs `next build` + `vitest`.
run_until loops until both pass. (E2E/Playwright is a later, heavier oracle.)
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from area.engine import build_agent, command_verifier, run_until
from area.spec.models import Acceptance, Spec

# Guarded install (only if node_modules missing) + build + tests. Exit 0 = pass.
_ORACLE_CMD = [
    "bash",
    "-lc",
    "[ -d node_modules ] || npm install --no-audit --no-fund; "
    "npm run build && npm test",
]


def _prompt(spec: Spec, acc: Acceptance) -> str:
    spec_yaml = yaml.safe_dump(spec.model_dump(), sort_keys=False)
    acc_yaml = yaml.safe_dump(acc.model_dump(), sort_keys=False)
    return f"""You are the build stage of a software factory. Build a working \
Next.js app in the CURRENT WORKING DIRECTORY that implements this spec.

=== spec.yaml ===
{spec_yaml}
=== acceptance.yaml ===
{acc_yaml}

Requirements:
- Next.js (App Router) + TypeScript, using npm. No external services, no auth,
  single user. A simple in-memory or file/SQLite store is fine.
- Put the domain logic in a pure, importable module (e.g. lib/todos.ts) with one
  function per feature, so it is unit-testable WITHOUT a browser.
- Wire a minimal UI (app/page.tsx) to those functions.
- Use Vitest. Under __tests__/, write tests that assert EACH acceptance
  criterion (AC-*) at the logic/API level (no browser/E2E).
- package.json scripts MUST include exactly:
    "build": "next build"
    "test":  "vitest run"
- Make `npm install`, `npm run build`, and `npm test` all succeed. Run them
  yourself and fix until green.

Keep it minimal and faithful to the spec. Do not invent scope.
"""


def build_app(
    spec: Spec,
    acc: Acceptance,
    app_dir: str | Path,
    *,
    backend: str = "acp",
    model: Optional[str] = None,
    max_iters: int = 3,
) -> bool:
    """Scaffold + self-correct a Next.js app until `next build` + Vitest pass."""
    app = Path(app_dir)
    app.mkdir(parents=True, exist_ok=True)
    oracle = command_verifier(_ORACLE_CMD, cwd=app)

    agent = build_agent(backend, model=model)
    try:
        passed, _ = run_until(
            agent, app, _prompt(spec, acc), oracle, max_iters=max_iters
        )
    finally:
        agent.close()
    return passed
