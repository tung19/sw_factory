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


# Wall clock for one provider-CLI invocation.
_CLI_TIMEOUT_S = 900.0


def _env() -> dict[str, str]:
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


def _capped(cmd: list[str], *, cwd: Path, env: dict[str, str], what: str,
            ) -> "subprocess.CompletedProcess[str]":
    """Run a provider CLI with a wall clock, returning a FAILED CompletedProcess on
    timeout instead of raising. Callers here only inspect returncode/stdout, so a
    synthesised failure keeps every call site's contract intact while making a hung
    CLI impossible."""
    try:
        return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                              env=env, timeout=_CLI_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            cmd, 124,
            f"{what} TIMED OUT after {_CLI_TIMEOUT_S:.0f}s and was killed", "")


def _vercel(app: Path, args: str) -> subprocess.CompletedProcess[str]:
    """Run `npx vercel <args>`. Auth comes from the VERCEL_TOKEN env var (the CLI
    reads it automatically; _env() propagates it) or a prior `vercel login` — never
    a `--token` CLI flag, which would leak the secret into the process table and
    any captured command output."""
    return _capped(
        ["bash", "-lc", f"npx -y vercel {args} 2>&1"],
        cwd=app, env=_env(), what=f"vercel {args.split()[0] if args else ''}")


def _vercel_env_add(app: Path, key: str, value: str, target: str = "production") -> subprocess.CompletedProcess[str]:
    """Set a project env var on Vercel, feeding the VALUE through stdin (never the
    argv/`ps` — same discipline as the token). `vercel env add` reads the value
    from stdin when the input isn't a TTY. Idempotent-ish: a pre-existing key makes
    the CLI error, which the caller treats as non-fatal."""
    e = _env()
    e["AREA_ENV_VAL"] = value
    return _capped(
        ["bash", "-lc",
         f'printf %s "$AREA_ENV_VAL" | npx -y vercel env add {shlex.quote(key)} {shlex.quote(target)} 2>&1'],
        cwd=app, env=e, what=f"vercel env add {key}")


def _provided_pg_url() -> Optional[str]:
    """A Postgres connection string the operator handed us (any provider — Neon,
    Supabase, …), to WIRE into the project. AREA_POSTGRES_URL wins over POSTGRES_URL."""
    for k in ("AREA_POSTGRES_URL", "POSTGRES_URL"):
        v = (os.getenv(k) or "").strip()
        if v:
            return v
    return None


def _apply_sql(app: Path, url: str, rel: str) -> bool:
    """Apply one SQL file to the Postgres URL via psql, as ONE transaction
    (`--single-transaction` + `ON_ERROR_STOP`), so a mid-file error rolls the whole
    file back instead of committing a half-applied schema. The URL goes through env
    (never interpolated into the shell) to survive a connection string's special
    chars. Idempotent iff the schema uses IF NOT EXISTS — which keeps psql
    error-free (returncode 0). A real error (including an "already exists" from a
    NON-idempotent statement) now rolls back and is reported as FAILURE, rather
    than being silently swallowed by an "already exists" substring check that let a
    partial apply pass as success."""
    e = _env()
    e["AREA_PG_URL"] = url
    # Capped: this applies a schema to PRODUCTION. A timeout leaves the single
    # transaction to be rolled back by the server, so report failure.
    p = _capped(
        ["bash", "-lc",
         f'psql "$AREA_PG_URL" --single-transaction -v ON_ERROR_STOP=1 '
         f'-f {shlex.quote(rel)} 2>&1'],
        cwd=app, env=e, what=f"psql -f {rel}")
    return p.returncode == 0


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
    url = None
    for k in _PG_URL_KEYS:
        v = _env_file_value(app, k)
        if v:
            url = v
            break
    if not url:
        provided = _provided_pg_url()
        if provided:
            # Wire an operator-supplied connection string into the project so the
            # deployed app gets POSTGRES_URL — no manual Marketplace step needed.
            _vercel_env_add(app, "POSTGRES_URL", provided, "production")
            url = provided
            log.append("POSTGRES_URL wired into project from AREA_POSTGRES_URL/POSTGRES_URL "
                       "(vercel env add, value via stdin)")
        else:
            log.append(
                "POSTGRES_URL not found after `vercel env pull` — either export "
                "AREA_POSTGRES_URL=<connection string> (AREA will wire it in) or "
                "connect a Postgres store (Vercel Marketplace → Neon) to this project, "
                "then re-run. NON-FATAL: deploy proceeds; DB calls fail until a store exists."
            )
            return True, "\n".join(log)
    else:
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
    first-time project linking. Auth is taken from the env (never a --token flag).
    """
    app = Path(app_dir)
    cmd = ["bash", "-lc", "npx -y vercel deploy --prod --yes 2>&1"]
    # Capped: a wrangler/vercel CLI waiting on a prompt or a stuck upload would
    # otherwise hang the deploy indefinitely.
    try:
        proc = subprocess.run(cmd, cwd=str(app), capture_output=True, text=True,
                              env=_env(), timeout=_CLI_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        # Report a stuck CLI as a failed deploy instead of letting the exception
        # escape — the caller's contract is (ok, log, url).
        return False, (f"vercel TIMED OUT after {_CLI_TIMEOUT_S:.0f}s and was killed "
                       "— deploy not confirmed; check the Vercel dashboard before "
                       "retrying."), None
    out = (proc.stdout + "\n" + proc.stderr).strip()
    m = _URL_RE.search(out)
    return proc.returncode == 0, out[-4000:], (m.group(0) if m else None)
