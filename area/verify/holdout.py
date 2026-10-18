"""area.verify — holdout acceptance verification (anti self-certification).

PLAN §1 warns: do not let the implementing LLM certify itself by writing the
tests it must pass. `area/build` lets the agent write its own quick tests to
iterate — fine for getting something working, but NOT a trustworthy "done".

This module adds an INDEPENDENT gate:
  1. a separate VERIFIER agent writes acceptance tests from acceptance.yaml,
  2. those tests are CHECKSUM-LOCKED under __tests__/_holdout/,
  3. a FIXER agent must make them pass by editing APP CODE ONLY; the oracle
     rejects any run where the holdout files changed.

So "done" means an independently-authored, unmodified test suite passes.
"""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Optional

from area._util import safe_name
from area.engine import VerifyResult, build_agent, run_once, run_until
from area.pipeline import WORKSPACE

HOLDOUT_DIR = "__tests__/_holdout"


def _lock(holdout: Path) -> dict:
    return {
        str(f.relative_to(holdout)): hashlib.sha256(f.read_bytes()).hexdigest()
        for f in sorted(holdout.rglob("*"))
        if f.is_file()
    }


def holdout_verify(
    name: str,
    *,
    backend: str = "acp",
    model: Optional[str] = None,
    max_iters: int = 3,
) -> bool:
    """Independently verify a built app against its acceptance criteria.

    Returns True only if an independently-authored, unmodified holdout test
    suite passes. Raises if there is no app/spec.
    """
    name = safe_name(name)
    app = WORKSPACE / "apps" / name
    acc_path = WORKSPACE / "specs" / name / "acceptance.yaml"
    if not app.exists():
        raise RuntimeError(f"no app at {app}")
    if not acc_path.exists():
        raise RuntimeError(f"no acceptance.yaml at {acc_path}")
    acc_yaml = acc_path.read_text()
    holdout = app / HOLDOUT_DIR
    holdout.mkdir(parents=True, exist_ok=True)

    # 1) VERIFIER agent authors holdout tests only
    vtask = (
        "You are an INDEPENDENT acceptance verifier (NOT the implementer). "
        f"Write Vitest acceptance tests under {HOLDOUT_DIR}/ that assert EACH "
        "acceptance criterion below against the app's REAL modules (import its "
        "lib/domain functions as the app exposes them). One `describe` per AC, "
        "strict and faithful. Do NOT modify any app source code — ONLY create "
        f"test files under {HOLDOUT_DIR}/. After writing, STOP.\n\n"
        f"=== acceptance.yaml ===\n{acc_yaml}"
    )
    vagent = build_agent(backend, model=model)
    try:
        run_once(vagent, app, vtask)
    finally:
        vagent.close()
    if not any(holdout.rglob("*.ts")) and not any(holdout.rglob("*.js")):
        raise RuntimeError("verifier agent produced no holdout tests")
    lock = _lock(holdout)
    print(f"[area] holdout: locked {len(lock)} test file(s) under {HOLDOUT_DIR}/")

    test_cmd = ["bash", "-lc", f"npx vitest run {HOLDOUT_DIR}"]

    def oracle() -> VerifyResult:
        if _lock(holdout) != lock:
            return VerifyResult(
                False,
                f"FORBIDDEN: files under {HOLDOUT_DIR}/ were modified. Those are "
                "the locked acceptance tests — revert them and fix APP CODE only.",
            )
        try:
            proc = subprocess.run(
                test_cmd, cwd=str(app), capture_output=True, text=True
            )
        except OSError as e:
            return VerifyResult(False, f"holdout runner failed: {e}")
        out = (proc.stdout + "\n" + proc.stderr).strip()
        return VerifyResult(proc.returncode == 0, out[-4000:])

    # Already passing? (the honest, best case)
    if oracle().ok:
        print("[area] holdout: PASS on first check (app already satisfies ACs)")
        return True

    # 2) FIXER agent: make holdout pass, APP CODE ONLY (holdout locked)
    ftask = (
        f"Independent acceptance tests under {HOLDOUT_DIR}/ are FAILING. Fix the "
        f"APP CODE so they pass. You MUST NOT edit, delete, rename, or weaken "
        f"anything under {HOLDOUT_DIR}/ — they are locked acceptance tests. "
        f"Check with `npx vitest run {HOLDOUT_DIR}`."
    )
    fagent = build_agent(backend, model=model)
    try:
        passed, _ = run_until(fagent, app, ftask, oracle, max_iters=max_iters)
    finally:
        fagent.close()
    print(f"[area] holdout: {'PASS' if passed else 'FAIL'}")
    return passed
