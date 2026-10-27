"""area.verify.audit — security + static-analysis gate (A), two-tier.

TIER 1 (deterministic, HARD BLOCK): tsc (types), `npm audit` (dependency CVEs at a
severity threshold), and a hardcoded-secrets scan. This is the reliable halt.
TIER 2: a risky-pattern review of the generated source (eval, shell exec,
dangerouslySetInnerHTML, SQL string-interpolation, Math.random for secrets). The
INJECTION class (XSS / eval / SQL-injection) BLOCKS by default; the rest
(shell-exec, weak-random) are advisory unless strict=True. Whatever blocks in the
current posture is part of the gate's ORACLE (`_audit_oracle`) — not a decision
taken next to it — so the gate can never print `BLOCK` and then return PASS.

With fix=True an agent resolves the fixable issues and the gate re-runs.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from area._util import safe_name
from area.engine import (
    Backend, VerifyResult, Verifier, build_agent, command_verifier, run_until,
)
from area.paths import WORKSPACE  # noqa: E402 (leaf single-source; avoids importing the whole pipeline+SDK behind a gate)

_LEVELS = ("low", "moderate", "high", "critical")


# Hardcoded-secret detection for the tier-1 BLOCKING scan. `[[:space:]]*` around
# the `[:=]` separator catches the common `KEY = "literal"` form (a spaced `=`,
# the Prettier/standard JS default) that a bare `[:=]` silently missed.
_SECRET_RE = (r"(api[_-]?key|secret|password|access[_-]?token)"
              r"[\"']?[[:space:]]*[:=][[:space:]]*[\"' ]*[A-Za-z0-9/+_.=-]{16,}")
# Substrings that mark a NON-secret match (env lookups / obvious placeholders).
# NOTE: `import `/`from ` are deliberately NOT excluded — an import/from statement
# can't match _SECRET_RE's `keyword <sep> 16+ value` shape anyway, and the old
# bare substring dropped real hits on any line merely containing those words
# (e.g. `const apiKey="…"; // rotated from vault`).
_SECRET_EXCLUDE = r"process\.env|NEXT_PUBLIC|example|placeholder|dummy|changeme|your[_-]"


def _check(audit_level: str = "high") -> str:
    """Tier-1 deterministic check script, parametrized by npm-audit severity."""
    level = audit_level if audit_level in _LEVELS else "high"
    return r"""
set +e
fail=0
echo "== tsc --noEmit (locked holdout excluded) =="
if [ -f tsconfig.json ]; then
  npx tsc --noEmit > /tmp/_area_tsc.txt 2>&1; rc=$?
  if [ $rc -eq 0 ]; then
    echo "TSC: ok"
  else
    # The locked holdout is the ORACLE: run-verified by vitest, frozen (can't be
    # edited to fix a type nit). So IGNORE errors confined to __tests__/_holdout/.
    # But match BOTH file-location errors (`foo.ts(1,2): error TS...`) AND global/
    # config errors (`error TS18003: ...`), and if a non-zero exit yields NO
    # recognizable diagnostics at all (tsc crash, not installed, bad tsconfig),
    # FAIL — never mask a broken type-check as green.
    # Classify by the FILE-PATH field only (before the first "("), not the whole
    # line — otherwise a production error whose MESSAGE merely contains the string
    # "__tests__/_holdout/" (a string-literal type, an import path) would be
    # misclassified as a holdout error and silently ignored.
    all_err=$(grep -E 'error TS[0-9]' /tmp/_area_tsc.txt)
    prod_err=$(printf '%s\n' "$all_err" | grep -vE '^[^(]*__tests__/_holdout/' | grep -E 'error TS[0-9]')
    hold_err=$(printf '%s\n' "$all_err" | grep -E '^[^(]*__tests__/_holdout/')
    if [ -n "$prod_err" ]; then
      echo "$prod_err" | head -25; echo "TSC: FAIL"; fail=1
    elif [ -n "$hold_err" ]; then
      echo "(tsc errors are only inside the locked holdout oracle — ignored; run-verified by vitest)"
      echo "TSC: ok"
    else
      tail -25 /tmp/_area_tsc.txt
      echo "TSC: FAIL (tsc did not complete — crash / not installed / bad tsconfig)"; fail=1
    fi
  fi
else
  # No tsconfig: a pure-JS app is fine, but TypeScript files with no tsconfig are
  # UNCHECKED — fail rather than silently skip the only type gate.
  if find . -path ./node_modules -prune -o \( -name '*.ts' -o -name '*.tsx' \) -print 2>/dev/null | grep -q .; then
    echo "TSC: FAIL (no tsconfig.json but TypeScript files present — types unchecked)"; fail=1
  else echo "(no tsconfig, no TS files — skipped)"; fi
fi
echo "== npm audit (%LEVEL%+) =="
npm audit --audit-level=%LEVEL% > /tmp/_area_aud.txt 2>&1; rc=$?
tail -15 /tmp/_area_aud.txt
[ $rc -eq 0 ] && echo "AUDIT: ok" || { echo "AUDIT: FAIL (%LEVEL%+)"; fail=1; }
echo "== secrets scan =="
secret_hits=$( { grep -rnEi "%SECRET_RE%" app lib src components server pages 2>/dev/null; \
     grep -nEi "%SECRET_RE%" .env .env.* 2>/dev/null; } \
     | grep -viE "%SECRET_EXCLUDE%" | head -10)
if [ -n "$secret_hits" ]; then
  echo "$secret_hits"
  echo "SECRETS: FAIL (possible hardcoded secret)"; fail=1
else echo "SECRETS: ok"; fi
exit $fail
""".replace("%LEVEL%", level).replace("%SECRET_RE%", _SECRET_RE).replace(
        "%SECRET_EXCLUDE%", _SECRET_EXCLUDE)


# Tier-2 risky code patterns in the app's OWN source (not node_modules). The 3rd
# field marks the INJECTION class (XSS / code-eval / SQL-injection) that BLOCKS by
# default — a factory whose job is shipping web apps shouldn't green-light an app
# with an injection sink. The rest (shell-exec, weak-random) stay advisory unless
# --strict. `--no-block-injection` downgrades the injection class to advisory too.
_RISKY = [
    (re.compile(r"dangerouslySetInnerHTML"), "React XSS sink — dangerouslySetInnerHTML", True),
    (re.compile(r"\beval\s*\("), "eval() — code-injection risk", True),
    (re.compile(r"\bnew\s+Function\s*\("), "new Function() — dynamic code execution", True),
    # Shell exec only: child_process, or a STANDALONE exec* call. A method call
    # like `db.exec(...)` (node:sqlite) or `regexp.exec(...)` is NOT shell exec —
    # the negative lookbehind for `.`/word char skips those. `spawn`/`spawnSync`
    # are caught via the child_process keyword (not the bare-call list) because a
    # bare `spawn(...)` is common in redux-saga / xstate and is NOT shell exec.
    (re.compile(r"child_process|(?<![.\w])(?:execSync|execFileSync|execFile|exec)\s*\("),
     "shell exec — command-injection risk", False),
    (re.compile(r"Math\.random\s*\(\)"), "Math.random() — not cryptographically secure (use crypto)", False),
    (re.compile(r"(?:SELECT|INSERT|UPDATE|DELETE)\b[^;\n]*\$\{"), "SQL built via string interpolation — injection risk", True),
    (re.compile(r"(?:SELECT|INSERT|UPDATE|DELETE)\b[^;\n]*['\"`]\s*\+"), "SQL built via string concatenation — injection risk", True),
]
# Messages of the injection-class subset that blocks by default.
_INJECTION_MSGS = frozenset(msg for _rx, msg, block in _RISKY if block)
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
                for rx, msg, _block in _RISKY:
                    if rx.search(line):
                        out.append((rel, i, msg))
    return out


def _blocking_findings(findings: list[tuple[str, int, str]], *, strict: bool,
                       block_injection: bool) -> list[tuple[str, int, str]]:
    """Which tier-2 findings BLOCK the gate: the injection class (unless
    `block_injection` is off), plus everything when `strict`."""
    out = []
    for f in findings:
        is_injection = f[2] in _INJECTION_MSGS
        if strict or (is_injection and block_injection):
            out.append(f)
    return out


def _tier2_lines(findings: list[tuple[str, int, str]],
                 blocking: list[tuple[str, int, str]]) -> str:
    """The tier-2 section of the oracle's feedback — the same text the gate prints,
    so what the operator reads is exactly what the verdict was computed from."""
    if not findings:
        return "[area] audit tier-2: no risky patterns"
    block_set = set(blocking)
    head = (f"[area] audit tier-2 (security review): {len(findings)} finding(s), "
            f"{len(blocking)} BLOCKING")
    rows = [f"  {'❌ BLOCK' if f in block_set else '⚠ advisory'} {f[0]}:{f[1]} — {f[2]}"
            for f in findings[:20]]
    return "\n".join([head, *rows])


def _audit_oracle(app: Path, audit_level: str, *, strict: bool,
                  block_injection: bool) -> tuple[Verifier, dict[str, list[tuple[str, int, str]]]]:
    """The gate's oracle: tier-1 (tsc + npm audit + secrets) AND the tier-2 findings
    that BLOCK in this posture.

    Tier 2 MUST be part of the oracle, not a decision taken beside it. It used to be
    measured once up front and re-checked only under `strict`, while the fix loop ran
    against a tier-1-only oracle — so with tier-1 already green the loop passed on
    attempt 1 and the gate printed `❌ BLOCK` for every injection sink and then
    `audit: ✅ PASS`. A gate must grade what it prints.

    Returns the verifier and a dict the caller reads the latest findings from (for the
    fix task), so the scan is never run twice against different source.
    """
    tier1 = command_verifier(["bash", "-lc", _check(audit_level)], cwd=app)
    latest: dict[str, list[tuple[str, int, str]]] = {"findings": [], "blocking": []}

    def check() -> VerifyResult:
        r = tier1()
        findings = advisory_scan(app)
        blocking = _blocking_findings(findings, strict=strict,
                                      block_injection=block_injection)
        latest["findings"], latest["blocking"] = findings, blocking
        feedback = f"{r.feedback}\n{_tier2_lines(findings, blocking)}"
        return VerifyResult(r.ok and not blocking, feedback)

    return check, latest


def static_audit(
    name: str,
    *,
    fix: bool = False,
    backend: Backend = "acp",
    model: Optional[str] = None,
    max_iters: int = 3,
    audit_level: str = "high",
    strict: bool = False,
    block_injection: bool = True,
) -> bool:
    """Two-tier security + static-analysis gate. Returns True if it passes.

    Tier 1 (tsc/npm-audit/secrets) always blocks. Tier 2 (risky-pattern scan):
    the INJECTION class (XSS / eval / SQL-injection) BLOCKS by default; the rest
    (shell-exec, weak-random) are advisory unless strict=True. `block_injection=
    False` downgrades the injection class to advisory too.
    """
    name = safe_name(name)
    app = WORKSPACE / "apps" / name
    if not app.exists():
        raise RuntimeError(f"no app at {app}")
    oracle, latest = _audit_oracle(app, audit_level, strict=strict,
                                   block_injection=block_injection)

    r = oracle()
    print(r.feedback)
    findings, blocking = latest["findings"], latest["blocking"]

    if r.ok:
        suffix = " (tier-2 advisory only)" if findings else ""
        print(f"[area] audit: ✅ PASS (tsc + npm audit[{audit_level}+] + secrets){suffix}")
        return True
    if not fix:
        print("[area] audit: ❌ issues found (run with --fix to auto-fix)")
        return False

    tier2_task = ""
    if blocking:
        tier2_task = "\n- rework these risky patterns (tier-2), they BLOCK:\n" + "\n".join(
            f"  {rel}:{ln} — {msg}" for rel, ln, msg in blocking[:20]
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
    # No re-check needed: `oracle` IS tier-1 + blocking tier-2, so `passed` already
    # means both are clean. (This used to be a `strict`-only re-scan, which is why a
    # non-strict run could print BLOCK and still pass.)
    if not passed and latest["blocking"]:
        print(f"[area] audit: ❌ {len(latest['blocking'])} blocking tier-2 finding(s) remain")
    print(f"[area] audit: {'✅ PASS' if passed else '❌ FAIL'}")
    return passed
