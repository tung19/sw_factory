"""area.deploy — ship a built app to production (Cloudflare Workers or Vercel).

Build target decides the host: `cloudflare` → Workers (vinext, + D1 provisioning);
`vercel`/`plain` → vanilla Next.js → Vercel. `deploy_with_gate` auto-detects the
provider from the built app, so callers don't have to track it.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

from area.deploy import cloudflare, vercel
from area.deploy.cloudflare import deploy, rollback  # cloudflare deploy (monitor/back-compat)

__all__ = ["deploy", "deploy_with_gate", "rollback", "detect_provider"]


def detect_provider(app_dir: str | Path) -> str:
    """'cloudflare' for a vinext/Workers app, else 'vercel' (vanilla Next.js)."""
    app = Path(app_dir)
    if (app / "cloudflare.config.ts").exists():
        return "cloudflare"
    try:
        pkg = json.loads((app / "package.json").read_text())
        if "build:cf" in (pkg.get("scripts") or {}):
            return "cloudflare"
    except Exception:
        pass
    return "vercel"


def deploy_with_gate(
    app_dir: str | Path,
    *,
    confirm: Callable[[str], bool],
    provider: Optional[str] = None,
    require_provenance: Optional[bool] = None,
) -> tuple[bool, Optional[str]]:
    """Human gate, then deploy to the right provider (auto-detected if not given).

    Cloudflare path auto-provisions D1 first; Vercel path is a plain deploy.

    Provenance check (SLSA-style): before deploying, the built artifact is verified
    against its recorded provenance. A "mismatch" (the source changed since it was
    gated) blocks the deploy when require_provenance is set (flag or the
    AREA_REQUIRE_PROVENANCE env); "absent" only warns (back-compat).
    """
    import os

    app_dir = str(app_dir)
    provider = provider or detect_provider(app_dir)
    if not confirm(app_dir):
        print("[area] deploy cancelled by human gate.")
        return False, None

    if require_provenance is None:
        require_provenance = (os.getenv("AREA_REQUIRE_PROVENANCE") or "").strip().lower() in (
            "1", "true", "yes",
        )
    try:
        from area.provenance import verify_provenance

        status, detail = verify_provenance(app_dir)
        if status == "ok":
            print(f"[area] ✅ provenance ok — {detail}")
        elif status == "mismatch":
            print(f"[area] ❌ provenance MISMATCH:\n{detail}")
            if require_provenance:
                print("[area] refusing deploy (AREA_REQUIRE_PROVENANCE) — re-run the "
                      "build+gates to re-attest, then deploy.")
                return False, None
            print("[area] (advisory — set AREA_REQUIRE_PROVENANCE=1 to make this a hard block)")
        else:  # absent
            print(f"[area] ⚠ provenance: {detail}")
            if require_provenance:
                print("[area] refusing deploy (AREA_REQUIRE_PROVENANCE) — build through "
                      "AREA's gates first to record provenance.")
                return False, None
    except Exception as e:  # noqa: BLE001 — never block deploy on the checker itself
        print(f"[area] provenance check skipped (warn): {e}")

    if provider == "cloudflare":
        if cloudflare.needs_d1(app_dir):
            print("[area] D1 detected — provisioning database before deploy…")
            try:
                pok, plog = cloudflare.provision_d1(app_dir)
                print(f"[area] D1 provision ({'ok' if pok else 'warn'}):\n{plog}")
            except Exception as e:  # noqa: BLE001 — never block deploy on provisioning
                print(f"[area] D1 provision skipped (warn): {e}")
        ok, out, url = cloudflare.deploy(app_dir)
    else:
        # Vercel: auto-provision connected storage (Postgres/Neon, KV/Upstash)
        # before deploy, mirroring the D1 step. Non-fatal — never block on it.
        for need, prov, label in (
            (vercel.needs_postgres, vercel.provision_postgres, "Postgres"),
            (vercel.needs_kv, vercel.provision_kv, "KV/Redis"),
        ):
            try:
                if need(app_dir):
                    print(f"[area] {label} usage detected — provisioning before deploy…")
                    pok, plog = prov(app_dir)
                    print(f"[area] {label} provision ({'ok' if pok else 'warn'}):\n{plog}")
            except Exception as e:  # noqa: BLE001 — never block deploy on provisioning
                print(f"[area] {label} provision skipped (warn): {e}")
        ok, out, url = vercel.deploy(app_dir)

    if ok:
        print(f"[area] ✅ deployed to {provider}: {url or '(URL not parsed — see output)'}")
        if url:
            try:
                from area.monitor import record_deploy

                record_deploy(Path(app_dir).name, url)
            except Exception:
                pass
    else:
        print(f"[area] ❌ deploy failed ({provider}):\n{out}")
    return ok, url
