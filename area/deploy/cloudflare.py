"""area.deploy.cloudflare — deploy a built app to Cloudflare Workers.

Keyless: vinext's deploy helper authenticates via the Cloudflare `cf` CLI
(NOT wrangler) — run `cf auth login` once (e.g. the app's
./node_modules/.bin/cf auth login), or set CLOUDFLARE_API_TOKEN. Runs the app's
own `deploy` script (vinext-cloudflare). A human gate guards production.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Optional

# matches *.workers.dev and *.pages.dev deploy URLs
_URL_RE = re.compile(r"https://[A-Za-z0-9.\-]+\.(?:workers|pages)\.dev\S*")


def _env() -> dict[str, str]:
    """Env with the writable npm cache workaround (root-owned ~/.npm issue)."""
    e = dict(os.environ)
    e.setdefault("npm_config_cache", str(Path.home() / ".cache" / "npm-area"))
    return e


def _config_text(app: Path) -> str:
    out = []
    for cfg in ("cloudflare.config.ts", "wrangler.toml", "wrangler.jsonc", "wrangler.json"):
        p = app / cfg
        if p.exists():
            out.append(p.read_text(errors="ignore"))
    return "\n".join(out)


def needs_d1(app_dir: str | Path) -> bool:
    """True if the app binds a D1 database (or ships SQL migrations)."""
    app = Path(app_dir)
    if re.search(r"bindings\.d1\(|d1_databases|\.d1\(", _config_text(app)):
        return True
    mig = app / "migrations"
    return mig.is_dir() and any(mig.glob("*.sql"))


def d1_db_names(app_dir: str | Path) -> list[str]:
    """Best-effort D1 database name(s): explicit database_name, else the worker
    `name`, else the app dir name (used for `wrangler d1 create <name>`)."""
    t = _config_text(Path(app_dir))
    names = set(re.findall(r'database_name\s*[:=]\s*["\']([A-Za-z0-9_.\-]+)["\']', t))
    if not names:
        m = re.search(r'name\s*[:=]\s*["\']([A-Za-z0-9_.\-]+)["\']', t)
        if m:
            names.add(m.group(1))
    if not names:
        names.add(Path(app_dir).name)
    return sorted(names)


def provision_d1(app_dir: str | Path) -> tuple[bool, str]:
    """Ensure each D1 database exists + apply migrations, BEFORE deploy.

    Uses wrangler (the app's own migration file documents
    `npx wrangler d1 migrations apply`); needs `npx wrangler login`. Idempotent:
    an already-existing DB counts as success. NON-FATAL by design — if
    wrangler/auth is missing or a step warns, we log and let deploy proceed,
    because vinext's `cf` deploy binds the D1 and the app creates its table
    lazily on first use. The essential guarantee is that the D1 DB EXISTS.
    """
    app = Path(app_dir)
    if not needs_d1(app):
        return True, "no D1 binding/migrations detected — skipped"
    ok_all = True
    log: list[str] = []
    has_mig = (app / "migrations").is_dir()
    for db in d1_db_names(app):
        c = subprocess.run(
            ["bash", "-lc", f"printf 'y\\n' | npx -y wrangler d1 create {db} 2>&1"],
            cwd=str(app), capture_output=True, text=True, env=_env(),
        )
        cout = (c.stdout + c.stderr).lower()
        created = c.returncode == 0 or "already exists" in cout
        ok_all = ok_all and created
        log.append(f"d1 create {db}: {'ok' if created else 'FAILED'}")
        if has_mig:
            # Apply each schema file with `d1 execute --file` (works WITHOUT a
            # wrangler.toml, unlike `d1 migrations apply`). Idempotent because the
            # generated schema uses CREATE TABLE IF NOT EXISTS.
            sqls = sorted((app / "migrations").glob("*.sql"))
            applied = 0
            for sql in sqls:
                m = subprocess.run(
                    ["bash", "-lc",
                     f"printf 'y\\n' | npx -y wrangler d1 execute {db} --remote "
                     f"--file=migrations/{sql.name} 2>&1"],
                    cwd=str(app), capture_output=True, text=True, env=_env(),
                )
                out = (m.stdout + m.stderr).lower()
                if m.returncode == 0 or "already exists" in out:
                    applied += 1
                else:
                    ok_all = False
            log.append(f"d1 migrate {db}: applied {applied}/{len(sqls)} schema file(s)")
    return ok_all, "\n".join(log)


def deploy(app_dir: str | Path) -> tuple[bool, str, Optional[str]]:
    """Run the app's Cloudflare deploy. Returns (ok, output_tail, url).

    Requires a prior `cf auth login` (or CLOUDFLARE_API_TOKEN). Prefers the
    app's `npm run deploy` script, falling back to `npx @vinext/cloudflare deploy`.
    """
    app = Path(app_dir)
    cmd = [
        "bash",
        "-lc",
        "npm run deploy 2>&1 || npx -y @vinext/cloudflare deploy 2>&1",
    ]
    proc = subprocess.run(
        cmd, cwd=str(app), capture_output=True, text=True, env=_env()
    )
    out = (proc.stdout + "\n" + proc.stderr).strip()
    m = _URL_RE.search(out)
    return proc.returncode == 0, out[-4000:], (m.group(0) if m else None)


def rollback(app_dir: str | Path, *, version: Optional[str] = None) -> tuple[bool, str]:
    """Roll a deployed Worker back to its previous (or a specific) version.

    Server-side via `wrangler rollback` — no rebuild. Needs a wrangler login
    (`npx wrangler login`). Run inside the app dir so wrangler finds the worker.
    """
    app = Path(app_dir)
    ver = f" {version}" if version else ""
    cmd = [
        "bash", "-lc",
        f"printf 'y\\n' | npx -y wrangler rollback{ver} --message 'area rollback' 2>&1",
    ]
    proc = subprocess.run(cmd, cwd=str(app), capture_output=True, text=True, env=_env())
    out = (proc.stdout + "\n" + proc.stderr).strip()
    return proc.returncode == 0, out[-4000:]


# NOTE: the provider-dispatching `deploy_with_gate` now lives in area/deploy/__init__.py
# (it auto-detects cloudflare vs vercel). This module keeps the Cloudflare-specific
# pieces: deploy(), rollback(), needs_d1(), provision_d1().
