"""area.verify.e2e — Playwright end-to-end parity verification (P4).

Unit/holdout tests (P1) assert logic. This asserts the REAL UI behaviour: an
agent sets up Playwright (with a webServer that boots the app), writes one E2E
spec per acceptance criterion that drives the UI (fill forms, click, read the
page), and the oracle runs `npx playwright test` until green.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from area._util import safe_name
from area.engine import build_agent, command_verifier, run_until
from area.pipeline import WORKSPACE
from area.verify.perf import _free_port

E2E_DIR = "e2e"


def e2e_verify(
    name: str,
    *,
    backend: str = "acp",
    model: Optional[str] = None,
    max_iters: int = 3,
) -> bool:
    """Set up Playwright and verify the app's UI against its acceptance criteria."""
    name = safe_name(name)
    app = WORKSPACE / "apps" / name
    acc_path = WORKSPACE / "specs" / name / "acceptance.yaml"
    if not app.exists():
        raise RuntimeError(f"no app at {app}")
    acc_yaml = acc_path.read_text() if acc_path.exists() else ""

    # Pin a free port: the framework default (:3000) is often taken (a local
    # Langfuse, another dev server), and reuseExistingServer:true would latch
    # onto that FOREIGN server and silently test the wrong app. Bind our own.
    port = _free_port()

    task = (
        "Add Playwright END-TO-END tests that drive the REAL UI of this app and "
        "assert EACH acceptance criterion below.\n"
        "- Install Playwright: `npm i -D @playwright/test` and "
        "`npx playwright install chromium`.\n"
        f"- IMPORTANT: port 3000 may be taken on this machine. Use port {port} "
        f"for EVERYTHING. In playwright.config.ts set `use.baseURL = "
        f"'http://localhost:{port}'` and a `webServer` block "
        f"`{{ command: <dev command bound to port {port}>, "
        f"url: 'http://localhost:{port}', reuseExistingServer: false, "
        f"timeout: 120000 }}` — the dev command is framework-specific (Next: "
        f"`npm run dev -- -p {port}`; Vite: `npm run dev -- --port {port}`). Do "
        "NOT use port 3000 and do NOT set reuseExistingServer:true (it would "
        "reuse a foreign server already on that port).\n"
        f"- One spec per AC under {E2E_DIR}/ . Interact THROUGH the UI (goto, "
        "fill, click, expect visible text) — do NOT import internal modules.\n"
        "- Make `npx playwright test` pass. Run it yourself and fix the APP and "
        "tests until green.\n\n"
        f"=== acceptance.yaml ===\n{acc_yaml}"
    )
    oracle = command_verifier(["bash", "-lc", "npx playwright test 2>&1"], cwd=app)

    agent = build_agent(backend, model=model)
    try:
        passed, _ = run_until(
            agent, app, task, oracle, max_iters=max_iters, label="e2e"
        )
    finally:
        agent.close()
    print(f"[area] e2e: {'PASS' if passed else 'FAIL'}")
    return passed
