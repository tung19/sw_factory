"""area.build.cf_scaffold — DETERMINISTIC fixes for the recurring Cloudflare
(vinext) build gotchas, so they stop depending on the build agent following the
`vinext-cf-build` skill by hand (PR2 §11: stabilise the beta vinext dependency).

Two fixes, both pure / idempotent and unit-testable WITHOUT a live build:

1. `pin_compat_date(app)` — `vinext init` writes `compatibilityDate = today`, but
   a date AHEAD of the installed `workerd` fails `vite build`. workerd versions
   ARE dates (`1.YYYYMMDD.N`), so the correct compat date is deterministic: read
   the installed workerd version and rewrite `compatibilityDate` in
   cloudflare.config.ts (and `compatibility_date` in a wrangler config) to its
   `YYYY-MM-DD`. No guessing, no agent.

2. `apply_cve_overrides(app)` — `npm audit --audit-level=high` hard-fails every
   vinext app via the unpatched `braces` CVE in build tooling. Merge the two
   package.json overrides the skill prescribes — `fflate ^0.7.5` and
   `braces file:./vendor/braces` — so the audit chain clears. (Vendoring the
   PATCHED braces source is still the skill/agent's job — see vinext-cf-build §3;
   this only wires the overrides deterministically.)

`harden_cf_app(app)` runs both and returns a summary. The Cloudflare deploy path
calls it as a safety net before deploy; `area cf-fix <name>` runs it standalone.
This is the deterministic SLICE of PR2 — the full `vinext init` → clone-a-known-
good-sibling-toolchain fallback (vinext-cf-build §2) needs a committed CF sibling
+ a live build to validate and is intentionally left to a follow-up.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Optional

# the two overrides that clear `npm audit --audit-level=high` for a vinext app
_CVE_OVERRIDES = {"fflate": "^0.7.5", "braces": "file:./vendor/braces"}

_COMPAT_RE = re.compile(
    r'(compatibilityDate|compatibility_date)(\s*[:=]\s*)(["\'])(\d{4}-\d{2}-\d{2})(["\'])'
)


def _env() -> dict[str, str]:
    e = dict(os.environ)
    e.setdefault("npm_config_cache", str(Path.home() / ".cache" / "npm-area"))
    return e


def date_from_workerd_version(version: str) -> Optional[str]:
    """workerd versions are dates: `1.YYYYMMDD.N` → `YYYY-MM-DD`. None if the
    middle component isn't an 8-digit date."""
    parts = version.strip().split(".")
    if len(parts) < 2:
        return None
    d = parts[1]
    if len(d) != 8 or not d.isdigit():
        return None
    y, mo, day = d[0:4], d[4:6], d[6:8]
    if not ("2000" <= y <= "2099" and "01" <= mo <= "12" and "01" <= day <= "31"):
        return None
    return f"{y}-{mo}-{day}"


def _find_workerd(node: dict[str, Any]) -> Optional[str]:
    """Walk an `npm ls --json` tree for workerd's resolved version."""
    deps = node.get("dependencies")
    if not isinstance(deps, dict):
        return None
    info = deps.get("workerd")
    if isinstance(info, dict) and "version" in info:
        return str(info["version"])
    for sub in deps.values():
        if isinstance(sub, dict):
            found = _find_workerd(sub)
            if found:
                return found
    return None


def workerd_version(app: Path) -> Optional[str]:
    """The installed workerd version in `app` (via `npm ls workerd`), or None."""
    try:
        p = subprocess.run(["npm", "ls", "workerd", "--json"], cwd=str(app),
                           capture_output=True, text=True, env=_env())
        if p.stdout.strip():
            found = _find_workerd(json.loads(p.stdout))
            if found:
                return found
    except (OSError, json.JSONDecodeError):
        pass
    try:
        p = subprocess.run(["npm", "ls", "workerd"], cwd=str(app),
                           capture_output=True, text=True, env=_env())
        m = re.search(r"workerd@(\d+\.\d+\.\d+)", p.stdout)
        if m:
            return m.group(1)
    except OSError:
        pass
    return None


def rewrite_compat_date(text: str, date: str) -> tuple[str, bool]:
    """Set every `compatibilityDate`/`compatibility_date` in `text` to `date`,
    preserving the original separator and quote style. Returns (new, changed)."""
    def repl(m: "re.Match[str]") -> str:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}{date}{m.group(5)}"

    new = _COMPAT_RE.sub(repl, text)
    return new, (new != text)


def pin_compat_date(app: Path, *, version: Optional[str] = None) -> Optional[str]:
    """Rewrite the app's compat date to the installed workerd's release date.
    Returns the date written, or None if workerd/the date/a config wasn't found.
    `version` is injectable for tests (skips the `npm ls` subprocess)."""
    ver = version or workerd_version(app)
    if not ver:
        return None
    date = date_from_workerd_version(ver)
    if not date:
        return None
    changed_any = False
    for cfg in ("cloudflare.config.ts", "wrangler.toml", "wrangler.jsonc",
                "wrangler.json"):
        p = app / cfg
        if not p.exists():
            continue
        new, changed = rewrite_compat_date(p.read_text(), date)
        if changed:
            p.write_text(new)
            changed_any = True
    return date if changed_any else None


def apply_cve_overrides(app: Path) -> bool:
    """Merge the braces/fflate npm overrides into package.json so the audit chain
    clears. Idempotent. Returns True if package.json changed."""
    pkg_path = app / "package.json"
    if not pkg_path.exists():
        return False
    try:
        pkg = json.loads(pkg_path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    overrides = pkg.get("overrides")
    if not isinstance(overrides, dict):
        overrides = {}
    changed = False
    for k, v in _CVE_OVERRIDES.items():
        if overrides.get(k) != v:
            overrides[k] = v
            changed = True
    if changed:
        pkg["overrides"] = overrides
        pkg_path.write_text(json.dumps(pkg, indent=2) + "\n")
    return changed


def harden_cf_app(app: str | Path, *, version: Optional[str] = None) -> dict[str, Any]:
    """Apply both deterministic vinext fixes. Safe to run repeatedly (idempotent)
    and on a non-CF app (it just reports nothing changed)."""
    ap = Path(app)
    date = pin_compat_date(ap, version=version)
    overrides = apply_cve_overrides(ap)
    summary: dict[str, Any] = {"compat_date": date, "cve_overrides": overrides}
    if date:
        print(f"[cf-fix] pinned compatibilityDate → {date} (from installed workerd)")
    if overrides:
        print("[cf-fix] applied braces/fflate npm overrides (clears the audit CVE chain)")
    if not date and not overrides:
        print("[cf-fix] nothing to change (compat date already pinned / overrides present / "
              "not a vinext app)")
    return summary
