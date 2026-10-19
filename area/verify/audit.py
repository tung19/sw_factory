"""area.verify.audit — security + static-analysis gate (A), two-tier.

TIER 1 (deterministic, HARD BLOCK): tsc (types), `npm audit` (dependency CVEs at a
severity threshold), and a hardcoded-secrets scan. This is the reliable halt.
TIER 2 (advisory): a risky-pattern review of the generated source (eval, shell
exec, dangerouslySetInnerHTML, SQL string-interpolation, Math.random for secrets).
Advisory by default (research: promote to blocking only after measuring FP rate);
with strict=True a tier-2 finding also blocks.

With fix=True an agent resolves the fixable issues and the gate re-runs.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from area._util import safe_name
from area.engine import build_agent, command_verifier, run_until
from area.pipeline import WORKSPACE

_LEVELS = ("low", "moderate", "high", "critical")


def _check(audit_level: str = "high") -> str:
    """Tier-1 deterministic check script, parametrized by npm-audit severity."""
    level = audit_level if audit_level in _LEVELS else "high"
    return r"""
set +e
fail=0
echo "== tsc --noEmit =="
if [ -f tsconfig.json ]; then
  npx tsc --noEmit > /tmp/_area_tsc.txt 2>&1; rc=$?
  tail -25 /tmp/_area_tsc.txt
  [ $rc -eq 0 ] && echo "TSC: ok" || { echo "TSC: FAIL"; fail=1; }
else echo "(no tsconfig)"; fi
echo "== npm audit (%LEVEL%+) =="
npm audit --audit-level=%LEVEL% > /tmp/_area_aud.txt 2>&1; rc=$?
tail -15 /tmp/_area_aud.txt
[ $rc -eq 0 ] && echo "AUDIT: ok" || { echo "AUDIT: FAIL (%LEVEL%+)"; fail=1; }
echo "== secrets scan =="
secret_hits=$(grep -rnEi "(api[_-]?key|secret|password|access[_-]?token)[\"']?[:=][\"' ]*[A-Za-z0-9_-]{16,}" app lib src components 2>/dev/null \
     | grep -viE "process\.env|NEXT_PUBLIC|example|placeholder|dummy|import |from " | head -10)
if [ -n "$secret_hits" ]; then
  echo "$secret_hits"
  echo "SECRETS: FAIL (possible hardcoded secret)"; fail=1
else echo "SECRETS: ok"; fi
exit $fail
""".replace("%LEVEL%", level)


# Tier-2 advisory: risky code patterns in the app's OWN source (not node_modules).
_RISKY = [
    (re.compile(r"dangerouslySetInnerHTML"), "React XSS sink — dangerouslySetInnerHTML"),
    (re.compile(r"\beval\s*\("), "eval() — code-injection risk"),
    (re.compile(r"\bnew\s+Function\s*\("), "new Function() — dynamic code execution"),
    (re.compile(r"child_process|\bexecSync\s*\(|\bexec\s*\("), "shell exec — command-injection risk"),
    (re.compile(r"Math\.random\s*\(\)"), "Math.random() — not cryptographically secure (use crypto)"),
    (re.compile(r"(?:SELECT|INSERT|UPDATE|DELETE)\b[^;\n]*\$\{"), "SQL built via string interpolation — injection risk"),
]
_SCAN_DIRS = ("app", "lib", "src", "components", "server", "pages")
_SCAN_EXT = {".ts", ".tsx", ".js", ".jsx", ".mjs"}


def advisory_scan(app_dir: str | Path) -> list[tuple[str, int, str]]:
    """Tier-2: list (relpath, line, message) risky-pattern findings in app source."""
    app = Path(app_dir)
    out: list[tuple[str, int, str]] = []
    for sub in _SCAN_DIRS:
        d = app / sub
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*")):
            if not p.is_file() or p.suffix not in _SCAN_EXT or "node_modules" in p.parts:
                continue
            try:
                lines = p.read_text(errors="ignore").splitlines()
            except OSError:
                continue
            rel = p.relative_to(app).as_posix()
            for i, line in enumerate(lines, 1):
                for rx, msg in _RISKY:
                    if rx.search(line):
                        out.append((rel, i, msg))
    return out


def static_audit(
    name: str,
    *,
    fix: bool = False,
    backend: str = "acp",
    model: Optional[str] = None,
    max_iters: int = 3,
    audit_level: str = "high",
    strict: bool = False,
) -> bool:
    """Two-tier security + static-analysis gate. Returns True if it passes.

    Tier 1 (tsc/npm-audit/secrets) always blocks. Tier 2 (risky-pattern scan) is
    advisory unless strict=True, in which case any tier-2 finding also blocks.
    """
    name = safe_name(name)
    app = WORKSPACE / "apps" / name
    if not app.exists():
        raise RuntimeError(f"no app at {app}")
    oracle = command_verifier(["bash", "-lc", _check(audit_level)], cwd=app)

    r = oracle()
    print(r.feedback)
    tier1_ok = r.ok

    # Tier 2 — advisory risky-pattern review.
    findings = advisory_scan(app)
    if findings:
        print(f"[area] audit tier-2 (advisory security review): {len(findings)} finding(s)"
              + (" — BLOCKING (strict)" if strict else " — advisory only"))
        for rel, ln, msg in findings[:20]:
            print(f"  ⚠ {rel}:{ln} — {msg}")
    else:
        print("[area] audit tier-2: no risky patterns")
    tier2_block = strict and bool(findings)

    if tier1_ok and not tier2_block:
        suffix = " (tier-2 advisory only)" if findings else ""
        print(f"[area] audit: ✅ PASS (tsc + npm audit[{audit_level}+] + secrets){suffix}")
        return True
    if not fix:
        print("[area] audit: ❌ issues found (run with --fix to auto-fix)")
        return False

    tier2_task = ""
    if tier2_block:
        tier2_task = "\n- rework these risky patterns (tier-2):\n" + "\n".join(
            f"  {rel}:{ln} — {msg}" for rel, ln, msg in findings[:20]
        )
    task = (
        "A security/static AUDIT of this app FAILED. Fix the issues and make the "
        "audit pass:\n"
        "- resolve all TypeScript errors (`npx tsc --noEmit`),\n"
        "- remove any hardcoded secrets (use env vars),\n"
        f"- address {audit_level}+ `npm audit` findings where safe (upgrade deps)."
        f"{tier2_task}\n\n"
        f"--- audit output ---\n{r.feedback}"
    )
    agent = build_agent(backend, model=model)
    try:
        passed, _ = run_until(
            agent, app, task, oracle, max_iters=max_iters, label="audit"
        )
    finally:
        agent.close()
    # Re-check tier-2 after the fix when strict.
    if passed and strict and advisory_scan(app):
        print("[area] audit: ❌ tier-2 risky patterns remain (strict)")
        return False
    print(f"[area] audit: {'✅ PASS' if passed else '❌ FAIL'}")
    return passed
