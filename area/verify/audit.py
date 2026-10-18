"""area.verify.audit — security + static-analysis gate (A).

Runs tsc (types), `npm audit` (dependency vulns), and a hardcoded-secrets scan
on a built app. A real engineering gate beyond "it builds + tests pass".
With fix=True an agent resolves the fixable issues and the gate re-runs.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from area._util import safe_name
from area.engine import build_agent, command_verifier, run_until
from area.pipeline import WORKSPACE

_CHECK = r"""
set +e
fail=0
echo "== tsc --noEmit =="
if [ -f tsconfig.json ]; then
  npx tsc --noEmit > /tmp/_area_tsc.txt 2>&1; rc=$?
  tail -25 /tmp/_area_tsc.txt
  [ $rc -eq 0 ] && echo "TSC: ok" || { echo "TSC: FAIL"; fail=1; }
else echo "(no tsconfig)"; fi
echo "== npm audit (high+) =="
npm audit --audit-level=high > /tmp/_area_aud.txt 2>&1; rc=$?
tail -15 /tmp/_area_aud.txt
[ $rc -eq 0 ] && echo "AUDIT: ok" || { echo "AUDIT: FAIL (high/critical)"; fail=1; }
echo "== secrets scan =="
if grep -rnEi "(api[_-]?key|secret|password|access[_-]?token)[\"']?[:=][\"' ]*[A-Za-z0-9_-]{16,}" app lib src components 2>/dev/null \
     | grep -viE "process\.env|NEXT_PUBLIC|example|placeholder|dummy|import |from " | head -10; then
  echo "SECRETS: FAIL (possible hardcoded secret)"; fail=1
else echo "SECRETS: ok"; fi
exit $fail
"""


def static_audit(
    name: str,
    *,
    fix: bool = False,
    backend: str = "acp",
    model: Optional[str] = None,
    max_iters: int = 3,
) -> bool:
    """Security + static-analysis gate. Returns True if clean."""
    name = safe_name(name)
    app = WORKSPACE / "apps" / name
    if not app.exists():
        raise RuntimeError(f"no app at {app}")
    oracle = command_verifier(["bash", "-lc", _CHECK], cwd=app)

    r = oracle()
    print(r.feedback)
    if r.ok:
        print("[area] audit: ✅ PASS (tsc + npm audit + secrets)")
        return True
    if not fix:
        print("[area] audit: ❌ issues found (run with --fix to auto-fix)")
        return False

    task = (
        "A security/static AUDIT of this app FAILED. Fix the issues and make the "
        "audit pass:\n"
        "- resolve all TypeScript errors (`npx tsc --noEmit`),\n"
        "- remove any hardcoded secrets (use env vars),\n"
        "- address high/critical `npm audit` findings where safe (upgrade deps).\n\n"
        f"--- audit output ---\n{r.feedback}"
    )
    agent = build_agent(backend, model=model)
    try:
        passed, _ = run_until(
            agent, app, task, oracle, max_iters=max_iters, label="audit"
        )
    finally:
        agent.close()
    print(f"[area] audit: {'✅ PASS' if passed else '❌ FAIL'}")
    return passed
