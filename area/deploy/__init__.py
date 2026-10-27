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


_NeedFn = Callable[["str | Path"], bool]
_ProvFn = Callable[["str | Path"], "tuple[bool, str]"]


def _provision_steps(provider: str) -> tuple[tuple[_NeedFn, _ProvFn, str], ...]:
    """The production datastores a deploy to `provider` creates/migrates."""
    if provider == "cloudflare":
        return ((cloudflare.needs_d1, cloudflare.provision_d1, "D1"),)
    return ((vercel.needs_postgres, vercel.provision_postgres, "Postgres"),
            (vercel.needs_kv, vercel.provision_kv, "KV/Redis"))


def _gate_description(app_dir: str, provider: str) -> str:
    """What the human is actually approving.

    The old prompt said "Cloudflare PRODUCTION" for every provider, and never
    mentioned that a PRODUCTION database would be created and migrated."""
    bits = [f"{Path(app_dir).name} → {provider} PRODUCTION"]
    stores: list[str] = []
    for need, _prov, label in _provision_steps(provider):
        try:
            if need(app_dir):
                stores.append(label)
        except Exception:  # noqa: BLE001 — detection must never break the prompt
            # not "{label}?" — the prompt itself ends in "?", so that reads as a
            # clean detection ("creates/migrates: Postgres?")
            stores.append(f"{label} (detection FAILED — assume yes)")
    if stores:
        bits.append("creates/migrates: " + ", ".join(stores))
    return " | ".join(bits)


def _provision(provider: str, app_dir: str, *, allow_failure: bool) -> bool:
    """Create/migrate the datastores the app needs. False ⇒ stop the deploy.

    This used to be "NON-FATAL by design": a failed migration still shipped, i.e.
    AREA deployed an app whose database was not there. A failed provision now blocks
    unless the caller explicitly allows it."""
    for need, prov, label in _provision_steps(provider):
        try:
            if not need(app_dir):
                continue
            print(f"[area] {label} needed — provisioning before deploy…")
            pok, plog = prov(app_dir)
        except Exception as e:  # noqa: BLE001
            pok, plog = False, f"{type(e).__name__}: {e}"
        if pok:
            print(f"[area] {label} provision ok:\n{plog}")
            continue
        print(f"[area] ❌ {label} provision FAILED:\n{plog}")
        if not allow_failure:
            print("[area] refusing deploy — shipping an app whose datastore was not "
                  "provisioned ships a broken app. Pass --allow-provision-failure "
                  "to deploy anyway.")
            return False
        print(f"[area] ⚠ continuing despite the {label} failure "
              "(--allow-provision-failure).")
    return True


def deploy_with_gate(
    app_dir: str | Path,
    *,
    confirm: Callable[[str], bool],
    provider: Optional[str] = None,
    require_provenance: Optional[bool] = None,
    allow_provision_failure: bool = False,
) -> tuple[bool, Optional[str]]:
    """Verify provenance, take a human gate, then deploy to the right provider.

    Order matters: the artifact is attested BEFORE a human is asked, so nobody is
    asked to approve a build that cannot ship, and the human gate stays the last
    word. The Cloudflare path provisions D1 first; the Vercel path provisions
    connected Postgres/KV.

    Provenance (SLSA-style): a "mismatch" (source changed since gating) ALWAYS
    refuses. "absent" (never gated through AREA) refuses too unless explicitly
    allowed — `require_provenance=False` or `AREA_REQUIRE_PROVENANCE=0`. A checker
    that cannot RUN also refuses: an enforcement point that is down must not pass.
    """
    import os

    app_dir = str(app_dir)
    provider = provider or detect_provider(app_dir)

    if require_provenance is None:
        env = (os.getenv("AREA_REQUIRE_PROVENANCE") or "").strip().lower()
        # Fail-CLOSED default: an ungated artifact does not ship unless asked for.
        require_provenance = env not in ("0", "false", "no")
    try:
        from area.provenance import verify_provenance

        status, detail = verify_provenance(app_dir)
        if status == "ok":
            print(f"[area] ✅ provenance ok — {detail}")
        elif status == "mismatch":
            # A mismatch means the artifact was MODIFIED after it was gated —
            # always refuse, regardless of the flag (the flag only governs the
            # weaker "absent provenance" case below).
            print(f"[area] ❌ provenance MISMATCH — artifact changed after gating:\n{detail}")
            print("[area] refusing deploy — re-run the build+gates to re-attest, then deploy.")
            return False, None
        else:  # absent
            print(f"[area] ⚠ provenance: {detail}")
            if require_provenance:
                print("[area] refusing deploy — this artifact was never gated through "
                      "AREA. Build through the gates to attest it, or pass "
                      "--no-require-provenance / AREA_REQUIRE_PROVENANCE=0 to ship "
                      "an unattested build deliberately.")
                return False, None
    except Exception as e:  # noqa: BLE001
        # The checker itself failing used to warn and deploy anyway — i.e. the one
        # enforcement point before production failed OPEN. It now refuses.
        print(f"[area] ❌ provenance check could not RUN: {e}")
        print("[area] refusing deploy — an enforcement point that is down must not pass.")
        return False, None

    if not confirm(_gate_description(app_dir, provider)):
        print("[area] deploy cancelled by human gate.")
        return False, None

    if not _provision(provider, app_dir, allow_failure=allow_provision_failure):
        return False, None

    if provider == "cloudflare":
        ok, out, url = cloudflare.deploy(app_dir)
    else:
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
