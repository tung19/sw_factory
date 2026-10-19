"""area.deploy.vercel — deploy a vanilla Next.js app ("plain"/"vercel" target) to Vercel.

Keyless: the Vercel CLI authenticates via `vercel login` (stores a token) or the
VERCEL_TOKEN env var. Runs `vercel deploy --prod` from the app dir. The human
gate lives in area.deploy.deploy_with_gate (the provider dispatcher).

Note: Vercel serverless has an ephemeral filesystem, so node:sqlite does NOT
persist there — a persistence app on Vercel needs Vercel Postgres/KV (a later
provisioning step, analogous to Cloudflare D1).
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Optional

_URL_RE = re.compile(r"https://[A-Za-z0-9.\-]+\.vercel\.app\S*")

# Source signals that an app needs durable Postgres (Vercel Postgres is now Neon
# via the Marketplace; @vercel/postgres is a thin wrapper over @neondatabase/serverless).
_PG_SIGNALS = re.compile(
    r"@vercel/postgres|@neondatabase/serverless|POSTGRES_URL|DATABASE_URL|"
    r"""from\s+['"]pg['"]|require\(['"]pg['"]\)|drizzle-orm/(?:neon|postgres)""",
    re.I,
)
# Signals for a Vercel KV / Upstash Redis store (KV is now Upstash via the Marketplace).
_KV_SIGNALS = re.compile(r"@vercel/kv|@upstash/redis|KV_REST_API_URL|KV_REST_API_TOKEN", re.I)

# Connection-string env vars a connected store exposes (first match wins).
_PG_URL_KEYS = ("POSTGRES_URL", "POSTGRES_URL_NON_POOLING", "POSTGRES_PRISMA_URL", "DATABASE_URL")
_KV_URL_KEYS = ("KV_REST_API_URL", "KV_URL", "REDIS_URL")


def _env() -> dict:
    e = dict(os.environ)
    e.setdefault("npm_config_cache", str(Path.home() / ".cache" / "npm-area"))
    return e


def _app_source_text(app: Path) -> str:
    """Concatenate the app's OWN source (never node_modules) for dependency sniffing:
    manifest/config/env files + a shallow scan of the usual code dirs."""
    chunks: list[str] = []
    for name in ("package.json", "vercel.json", ".env", ".env.local", ".env.production"):
        p = app / name
        if p.exists():
            chunks.append(p.read_text(errors="ignore"))
    for sub in ("app", "lib", "src", "pages", "server"):
        d = app / sub
        if not d.is_dir():
            continue
        for pat in ("*.ts", "*.tsx", "*.js", "*.mjs"):
            for f in sorted(d.rglob(pat))[:300]:
                if "node_modules" in f.parts:
                    continue
                try:
                    chunks.append(f.read_text(errors="ignore"))
                except Exception:  # noqa: BLE001
                    pass
    return "\n".join(chunks)


def _env_file_value(app: Path, key: str) -> Optional[str]:
    """Value of KEY from the app's pulled env files (handles `export ` + quotes)."""
    for name in (".env.local", ".env", ".env.production.local", ".env.development.local"):
        p = app / name
        if not p.exists():
            continue
        for raw in p.read_text(errors="ignore").splitlines():
            line = raw.strip()
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() == key:
                return v.strip().strip('"').strip("'")
    return None


def needs_postgres(app_dir: str | Path) -> bool:
    """True if the app persists via Postgres (SDK/driver/env ref) or ships SQL migrations."""
    app = Path(app_dir)
    if _PG_SIGNALS.search(_app_source_text(app)):
        return True
    mig = app / "migrations"
    return mig.is_dir() and any(mig.glob("*.sql"))


def needs_kv(app_dir: str | Path) -> bool:
    """True if the app uses a Vercel KV / Upstash Redis store."""
    return bool(_KV_SIGNALS.search(_app_source_text(Path(app_dir))))


def _vercel(app: Path, args: str):
    """Run `npx vercel <args>` (auth via VERCEL_TOKEN or a prior `vercel login`)."""
    token = os.getenv("VERCEL_TOKEN")
    tflag = f" --token {token}" if token else ""
    return subprocess.run(
        ["bash", "-lc", f"npx -y vercel {args}{tflag} 2>&1"],
        cwd=str(app), capture_output=True, text=True, env=_env(),
    )


def _apply_sql(app: Path, url: str, rel: str) -> bool:
    """Apply one SQL file to the Postgres URL via psql. Idempotent iff the schema
    uses IF NOT EXISTS. The URL is passed through env (never interpolated into the
    shell) to survive the special chars in a connection string."""
    e = _env()
    e["AREA_PG_URL"] = url
    p = subprocess.run(
        ["bash", "-lc", f'psql "$AREA_PG_URL" -v ON_ERROR_STOP=1 -f {shlex.quote(rel)} 2>&1'],
        cwd=str(app), capture_output=True, text=True, env=e,
    )
    out = (p.stdout + p.stderr).lower()
    return p.returncode == 0 or "already exists" in out


def provision_postgres(app_dir: str | Path) -> tuple[bool, str]:
    """Ensure a Postgres store is connected + apply migrations, BEFORE deploy.

    Mirrors cloudflare.provision_d1's contract: idempotent + NON-FATAL (never
    blocks deploy). The key difference from D1: Vercel no longer creates a
    database from the CLI — a Postgres store is provisioned through the Vercel
    Marketplace (Neon) and connected to the project; that injects POSTGRES_URL
    into the project env. So here we `vercel link` + `vercel env pull` to surface
    that URL, then apply `migrations/*.sql` against it. If the URL is absent the
    store isn't connected yet — we return a clear, actionable warning and let the
    deploy proceed (the app will error on DB calls until the store is connected).
    """
    app = Path(app_dir)
    if not needs_postgres(app):
        return True, "no Postgres usage detected — skipped"
    log: list[str] = []
    _vercel(app, "link --yes")
    log.append("vercel link: attempted")
    _vercel(app, "env pull .env.local --yes")
    url = next((_env_file_value(app, k) for k in _PG_URL_KEYS if _env_file_value(app, k)), None)
    if not url:
        log.append(
            "POSTGRES_URL not found after `vercel env pull` — connect a Postgres "
            "store (Vercel Marketplace → Neon) to this project, then re-run. "
            "NON-FATAL: deploy proceeds; DB calls will fail until the store is connected."
        )
        return True, "\n".join(log)
    log.append("POSTGRES_URL present")
    mig = app / "migrations"
    if mig.is_dir():
        sqls = sorted(mig.glob("*.sql"))
        applied = sum(1 for s in sqls if _apply_sql(app, url, f"migrations/{s.name}"))
        log.append(f"postgres migrate: applied {applied}/{len(sqls)} schema file(s)")
    return True, "\n".join(log)


def provision_kv(app_dir: str | Path) -> tuple[bool, str]:
    """Ensure a KV/Redis store is connected BEFORE deploy. NON-FATAL.

    KV has no SQL schema, so provisioning = confirming the store's REST env vars
    are present after `vercel env pull`. A missing store (now an Upstash Redis
    integration from the Marketplace) yields an actionable warning, not a failure.
    """
    app = Path(app_dir)
    if not needs_kv(app):
        return True, "no KV/Redis usage detected — skipped"
    log: list[str] = []
    _vercel(app, "link --yes")
    log.append("vercel link: attempted")
    _vercel(app, "env pull .env.local --yes")
    if any(_env_file_value(app, k) for k in _KV_URL_KEYS):
        log.append("KV/Redis env present")
        return True, "\n".join(log)
    log.append(
        "KV_REST_API_URL not found after `vercel env pull` — connect an Upstash "
        "Redis store (Vercel Marketplace) to this project. NON-FATAL."
    )
    return True, "\n".join(log)


def deploy(app_dir: str | Path) -> tuple[bool, str, Optional[str]]:
    """Deploy the app to Vercel production. Returns (ok, output_tail, url).

    Requires a prior `vercel login` (or VERCEL_TOKEN). `--yes` skips prompts for
    first-time project linking.
    """
    app = Path(app_dir)
    token = os.getenv("VERCEL_TOKEN")
    tflag = f" --token {token}" if token else ""
    cmd = ["bash", "-lc", f"npx -y vercel deploy --prod --yes{tflag} 2>&1"]
    proc = subprocess.run(cmd, cwd=str(app), capture_output=True, text=True, env=_env())
    out = (proc.stdout + "\n" + proc.stderr).strip()
    m = _URL_RE.search(out)
    return proc.returncode == 0, out[-4000:], (m.group(0) if m else None)
