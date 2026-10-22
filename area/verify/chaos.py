"""area.verify.chaos — chaos / resilience verification (B).

An agent writes Vitest chaos tests under __tests__/_chaos/ that fuzz the domain
with adversarial inputs, hammer it concurrently, and inject failures — asserting
the app degrades GRACEFULLY (never crashes, no corrupt state) — then makes the
app robust until they pass. This is chaos technical engineering ON the generated
app (not just happy-path tests).
"""
from __future__ import annotations

from typing import Optional

from area._util import safe_name
from area.engine import Backend, VerifyResult, build_agent, command_verifier, run_until
from area.paths import WORKSPACE  # noqa: E402 (leaf single-source; avoids importing the whole pipeline+SDK behind a gate)
from area.verify._runners import assert_vitest_ran

CHAOS_DIR = "__tests__/_chaos"


def chaos_verify(
    name: str,
    *,
    backend: Backend = "acp",
    model: Optional[str] = None,
    max_iters: int = 3,
) -> bool:
    """Chaos/resilience-test the app and harden it until the tests pass."""
    name = safe_name(name)
    app = WORKSPACE / "apps" / name
    if not app.exists():
        raise RuntimeError(f"no app at {app}")

    task = (
        f"Add CHAOS / RESILIENCE tests (Vitest) under {CHAOS_DIR}/ that stress the "
        "app's domain logic and assert it degrades GRACEFULLY — never throws "
        "unexpectedly, never leaves corrupt state. Cover:\n"
        "1. ADVERSARIAL / FUZZ inputs: empty, whitespace-only, very long strings "
        "(10k+ chars), unicode & emoji, control chars, HTML/JS/SQL-injection-like "
        "payloads, wrong types / null / undefined.\n"
        "2. CONCURRENCY: many interleaved operations (add/edit/delete) keep the "
        "store consistent — no lost, duplicated, or corrupted records; ids stay "
        "unique.\n"
        "3. FAILURE INJECTION: if an internal dependency throws, the operation "
        "fails cleanly and the store is left unchanged (no partial writes).\n\n"
        "Then HARDEN the app (validate/sanitize inputs, guard invariants, handle "
        f"errors) so `npx vitest run {CHAOS_DIR}` passes. Fix the app, not the "
        "tests' intent."
    )
    from area.memory import as_prompt, recall

    task = as_prompt(recall(tags=["chaos", "build"], text=name)) + task

    base = command_verifier(
        ["bash", "-lc", f"npx vitest run {CHAOS_DIR} 2>&1"], cwd=app
    )

    def oracle() -> VerifyResult:
        r = base()
        if r.ok:
            ran, why = assert_vitest_ran(r.feedback, 1)
            if not ran:
                return VerifyResult(False, f"chaos exit was green but {why} — the "
                                    "chaos suite must actually run.\n\n" + r.feedback[-2500:])
        return r

    agent = build_agent(backend, model=model)
    try:
        passed, _ = run_until(
            agent, app, task, oracle, max_iters=max_iters, label="chaos"
        )
    finally:
        agent.close()
    print(f"[area] chaos: {'✅ PASS' if passed else '❌ FAIL'}")
    return passed
