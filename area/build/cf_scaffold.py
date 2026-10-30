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
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from area.engine_util import scrubbed_env
from area._util import cmd_timeout_or_none
from typing import Any, Optional

# the two overrides that clear `npm audit --audit-level=high` for a vinext app
_CVE_OVERRIDES = {"fflate": "^0.7.5", "braces": "file:./vendor/braces"}

_COMPAT_RE = re.compile(
    r'(compatibilityDate|compatibility_date)(\s*[:=]\s*)(["\'])(\d{4}-\d{2}-\d{2})(["\'])'
)

# the committed patched-braces template (CVE depth-guard). Its braces deps live
# under `_deps/` (not `node_modules/`, which .gitignore would swallow); vendor_braces
# materialises them into `node_modules/` in the target app.
_TEMPLATE_BRACES = Path(__file__).resolve().parent / "templates" / "braces"

# a known-good CF toolchain is cloned file-for-file (vinext-cf-build §2): reusing a
# sibling's exact lockfile + node_modules pins the workerd the build already passes.
_TOOLCHAIN_FILES = (
    "package.json", "package-lock.json", "tsconfig.json", "next-env.d.ts",
    "next.config.ts", "next.config.mjs", "next.config.js",
    "vite.config.ts", "cloudflare.config.ts",
)
_TOOLCHAIN_DIRS = ("vendor", "node_modules")


def _env() -> dict[str, str]:
    # Built on `scrubbed_env()`, not `os.environ`: every command this module launches
    # runs the GENERATED app — agent-authored package.json scripts, so arbitrary
    # `postinstall`/build code — and must not inherit the deploy/cloud tokens this
    # process holds. Only those named keys are dropped; npm/node configuration and PATH
    # are preserved, which is what keeps the build working.
    e = scrubbed_env()
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


# `npm ls` reads the installed tree; it is not a build, so it should answer in seconds.
# Capped anyway: SECURITY.md claims every build/provider subprocess has a wall clock, and
# these two were the last that did not. A hung npm here would wedge `area cf-fix` with no
# output, and the compat-date pin is exactly the step a stuck build is waiting on.
_LS_TIMEOUT_S = 120.0


def workerd_version(app: Path) -> Optional[str]:
    """The installed workerd version in `app` (via `npm ls workerd`), or None."""
    try:
        p = subprocess.run(["npm", "ls", "workerd", "--json"], cwd=str(app),
                           capture_output=True, text=True, env=_env(),
                           timeout=_LS_TIMEOUT_S)
        if p.stdout.strip():
            found = _find_workerd(json.loads(p.stdout))
            if found:
                return found
    except (OSError, json.JSONDecodeError, subprocess.TimeoutExpired):
        # TimeoutExpired is a SubprocessError, not an OSError: without naming it the
        # timeout would escape this helper and crash the caller instead of degrading to
        # "version unknown", which is the whole point of the try/except here.
        pass
    try:
        p = subprocess.run(["npm", "ls", "workerd"], cwd=str(app),
                           capture_output=True, text=True, env=_env(),
                           timeout=_LS_TIMEOUT_S)
        m = re.search(r"workerd@(\d+\.\d+\.\d+)", p.stdout)
        if m:
            return m.group(1)
    except (OSError, subprocess.TimeoutExpired):
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


def _is_cf_app(app: Path) -> bool:
    """A vinext/Cloudflare app: has a cloudflare.config.ts or a vite config."""
    return (app / "cloudflare.config.ts").exists() or (app / "vite.config.ts").exists()


def harden_cf_app(app: str | Path, *, version: Optional[str] = None) -> dict[str, Any]:
    """Apply the deterministic vinext fixes. Safe to run repeatedly (idempotent)
    and on a non-CF app (it just reports nothing changed). For a CF app it also
    vendors the patched braces so the `braces: file:./vendor/braces` override it
    writes actually resolves."""
    ap = Path(app)
    date = pin_compat_date(ap, version=version)
    overrides = apply_cve_overrides(ap)
    vendored = vendor_braces(ap) if _is_cf_app(ap) else False
    summary: dict[str, Any] = {"compat_date": date, "cve_overrides": overrides,
                               "vendored_braces": vendored}
    if date:
        print(f"[cf-fix] pinned compatibilityDate → {date} (from installed workerd)")
    if overrides:
        print("[cf-fix] applied braces/fflate npm overrides (clears the audit CVE chain)")
    if vendored:
        print("[cf-fix] vendored patched braces → vendor/braces (CVE depth-guard)")
    if not date and not overrides and not vendored:
        print("[cf-fix] nothing to change (compat date already pinned / overrides present / "
              "not a vinext app)")
    return summary


def vendor_braces(app: str | Path) -> bool:
    """Copy the committed patched-braces template into <app>/vendor/braces so the
    `braces: file:./vendor/braces` override resolves offline, and materialise its
    bundled deps (fill-range/is-number/to-regex-range) from `_deps/` into
    `node_modules/` so the package is self-contained on first install. Idempotent;
    returns True if written. (The depth-guard patch fixes braces' deeply-nested
    stack-exhaustion CVE — the HIGH that `npm audit` flags for every vinext app.)"""
    ap = Path(app)
    if not _TEMPLATE_BRACES.is_dir():
        return False
    dst = ap / "vendor" / "braces"
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(_TEMPLATE_BRACES, dst)
    _materialise_braces_deps(dst)
    return True


def _materialise_braces_deps(braces_dir: Path) -> None:
    """Copy vendor/braces/_deps/* → vendor/braces/node_modules/* (npm resolves the
    latter; `_deps` is the gitignore-safe source that survives a parent prune)."""
    deps = braces_dir / "_deps"
    if not deps.is_dir():
        return
    nm = braces_dir / "node_modules"
    nm.mkdir(parents=True, exist_ok=True)
    for dep in deps.iterdir():
        if dep.is_dir():
            d = nm / dep.name
            if d.exists():
                shutil.rmtree(d)
            shutil.copytree(dep, d)


def restore_vendored_braces(app: str | Path) -> bool:
    """Re-seed vendor/braces/node_modules if a parent `npm install` pruned braces'
    transitive deps (the known fill-range prune — vinext-cf-build §4). Offline:
    re-materialises from the app's own `vendor/braces/_deps`. Returns True if a
    restore was needed and done."""
    ap = Path(app)
    braces = ap / "vendor" / "braces"
    if not braces.is_dir() or not (braces / "_deps").is_dir():
        return False
    if (braces / "node_modules" / "fill-range").is_dir():
        return False  # intact, nothing to do
    _materialise_braces_deps(braces)
    return True


def clone_sibling_toolchain(app: str | Path, sibling: str | Path) -> list[str]:
    """Clone a known-good CF toolchain from `sibling` into `app` — the
    vinext-cf-build §2 fallback: skip the fragile fresh `vinext init` and reuse a
    sibling that already builds green, pinning the exact workerd its lockfile +
    node_modules pair with. Copies the toolchain files/dirs that exist, then
    rewrites `name` in package.json and the worker `name` in cloudflare.config.ts
    to this app's basename. Returns the copied names."""
    ap, sib = Path(app), Path(sibling)
    copied: list[str] = []
    ap.mkdir(parents=True, exist_ok=True)
    for rel in _TOOLCHAIN_FILES:
        src = sib / rel
        if src.is_file():
            shutil.copy2(src, ap / rel)
            copied.append(rel)
    for rel in _TOOLCHAIN_DIRS:
        src = sib / rel
        if src.is_dir():
            dst = ap / rel
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst, symlinks=True)
            copied.append(rel + "/")
    name = ap.name
    pkg = ap / "package.json"
    if pkg.exists():
        try:
            j = json.loads(pkg.read_text())
            j["name"] = name
            pkg.write_text(json.dumps(j, indent=2) + "\n")
        except (OSError, json.JSONDecodeError):
            pass
    cfg = ap / "cloudflare.config.ts"
    if cfg.exists():
        t = cfg.read_text()
        t2 = re.sub(r'(\bname\s*:\s*)(["\'])[^"\']*(["\'])', rf'\1\2{name}\3', t, count=1)
        if t2 != t:
            cfg.write_text(t2)
    return copied


def _npm_run(app: Path, script: str) -> tuple[bool, str]:
    # Capped: this is the fallback BUILD (`npm run build:cf`), the longest command in
    # the CF path, and it had no wall clock at all.
    p = subprocess.run(["npm", "run", script], cwd=str(app),
                       capture_output=True, text=True, env=_env(),
                       timeout=cmd_timeout_or_none())
    return p.returncode == 0, (p.stdout + "\n" + p.stderr)[-4000:]


def build_cf_with_fallback(
    app: str | Path, *, sibling: Optional[str | Path] = None,
    build_script: str = "build:cf",
    runner: Optional[Callable[[Path, str], tuple[bool, str]]] = None,
) -> tuple[bool, str]:
    """Run the CF build; on failure, if a known-good `sibling` is given, clone its
    toolchain + re-harden + restore the vendored braces, then retry ONCE. `runner`
    is injectable for tests (default: `npm run <build_script>`). Returns
    (ok, log)."""
    ap = Path(app)
    run = runner or _npm_run
    ok, log = run(ap, build_script)
    if ok or sibling is None:
        return ok, log
    print(f"[cf] {build_script} failed — cloning known-good sibling toolchain "
          f"from {sibling} and retrying")
    clone_sibling_toolchain(ap, sibling)
    harden_cf_app(ap)
    restore_vendored_braces(ap)
    ok2, log2 = run(ap, build_script)
    return ok2, log + "\n--- after sibling-clone fallback ---\n" + log2
