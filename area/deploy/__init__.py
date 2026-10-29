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


def _settle_before_attesting(app_dir: str, provider: str) -> bool:
    """Run the deterministic CF safety net, then prove the app did NOT change.

    It used to run INSIDE `cloudflare.deploy()`, i.e. AFTER `verify_provenance` — so
    `harden_cf_app` could pin the compat date, write npm overrides and vendor braces,
    and those mutated bytes shipped while the attestation described the pre-hardened
    source. The record said "this is what was gated" about something else.

    Now it runs here, before verification, and any mutation REFUSES the deploy: if the
    safety net had to change an already-gated app, the gates judged different bytes
    than would ship. `_finish` hardens cloudflare builds before the gates, so in a
    normal flow this is a no-op tripwire rather than a blocker.

    The digest comparison is deliberately broader than the three things
    `harden_cf_app` reports: it catches ANY change under the app's source tree."""
    if provider != "cloudflare":
        return True
    from area.provenance import artifact_digest

    before = artifact_digest(app_dir)
    try:
        from area.build.cf_scaffold import harden_cf_app

        harden_cf_app(app_dir)
    except Exception as e:  # noqa: BLE001 — the net is a diagnostic, not a gate
        print(f"[area] cf-fix safety net skipped (warn): {e}")
        return True
    if artifact_digest(app_dir) == before:
        return True
    print("[area] ❌ the deterministic cf-fix had to CHANGE this app, and it was "
          "already gated — so the gates judged different bytes than would ship.")
    print("[area] refusing deploy. Run `area cf-fix <name>` (or rebuild), then re-run "
          "the gates so the attestation covers what actually deploys.")
    return False


def _resolve_require_provenance(require_provenance: Optional[bool]) -> bool:
    """None ⇒ let AREA_REQUIRE_PROVENANCE decide, fail-CLOSED (require) by default."""
    if require_provenance is not None:
        return require_provenance
    import os

    env = (os.getenv("AREA_REQUIRE_PROVENANCE") or "").strip().lower()
    return env not in ("0", "false", "no")


def _provenance_gate(
    app_dir: str, require_provenance: Optional[bool]
) -> tuple[bool, list[str]]:
    """The provenance decision as (would_proceed, lines_to_print). Pure and read-only:
    the real deploy and `--dry-run` both go through this, so a dry run's verdict can
    never diverge from what a real deploy would actually do (the exact drift the
    'a check reads a narrower surface than the thing it guards' bugs are made of)."""
    req = _resolve_require_provenance(require_provenance)
    try:
        from area.provenance import verify_provenance

        status, detail = verify_provenance(app_dir)
    except Exception as e:  # noqa: BLE001 — a checker that cannot RUN must not pass
        return False, [
            f"[area] ❌ provenance check could not RUN: {e}",
            "[area] refusing deploy — an enforcement point that is down must not pass.",
        ]
    if status == "ok":
        return True, [f"[area] ✅ provenance ok — {detail}"]
    if status == "mismatch":
        # Modified after gating — always refuse, regardless of the flag.
        return False, [
            f"[area] ❌ provenance MISMATCH — artifact changed after gating:\n{detail}",
            "[area] refusing deploy — re-run the build+gates to re-attest, then deploy.",
        ]
    if status == "stale-digest":
        # Attestation intact, but this AREA digests a different file set — unverifiable,
        # not drift. Same override as an unattested build; an explicit branch so a
        # status nobody anticipated can't fall through to fail-open.
        lines = [f"[area] ⚠ provenance UNVERIFIABLE — {detail}"]
        if req:
            lines.append(
                "[area] refusing deploy — re-run the build+gates to re-attest under the "
                "current digest definition, or pass --no-require-provenance to ship an "
                "unverified build deliberately. This is NOT evidence of tampering.")
            return False, lines
        return True, lines
    # absent
    lines = [f"[area] ⚠ provenance: {detail}"]
    if req:
        lines.append(
            "[area] refusing deploy — this artifact was never gated through AREA. Build "
            "through the gates to attest it, or pass --no-require-provenance / "
            "AREA_REQUIRE_PROVENANCE=0 to ship an unattested build deliberately.")
        return False, lines
    return True, lines


def _dry_run_plan(
    app_dir: str, provider: str, require_provenance: Optional[bool]
) -> tuple[bool, None]:
    """Print the deploy plan and change NOTHING: no CF hardening, no provisioning, no
    human prompt, no deploy. Returns (would_proceed, None) so the CLI exit code still
    says whether a real deploy would go ahead."""
    name = Path(app_dir).name
    print(f"[area] DRY RUN — planning a deploy of {name} to {provider}. "
          "Nothing will be created, migrated, hardened, or deployed.")
    proceed, lines = _provenance_gate(app_dir, require_provenance)
    for ln in lines:
        print(ln)
    stores: list[str] = []
    for need, _prov, label in _provision_steps(provider):
        try:
            if need(app_dir):
                stores.append(label)
        except Exception as e:  # noqa: BLE001 — a probe failure must not break the plan
            stores.append(f"{label} (detection FAILED: {type(e).__name__})")
    if stores:
        print(f"[area] would create/migrate PRODUCTION datastore(s): {', '.join(stores)}")
    else:
        print("[area] no PRODUCTION datastore provisioning needed.")
    print(f"[area] human-gate prompt would read: {_gate_description(app_dir, provider)!r}")
    if proceed:
        print(f"[area] ✅ plan OK — a real `area deploy {name}` would prompt the gate, "
              f"then deploy to {provider}.")
    else:
        print("[area] ⛔ a real deploy would REFUSE here — fix the reason above first.")
    return proceed, None


def deploy_with_gate(
    app_dir: str | Path,
    *,
    confirm: Callable[[str], bool],
    provider: Optional[str] = None,
    require_provenance: Optional[bool] = None,
    allow_provision_failure: bool = False,
    dry_run: bool = False,
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
    app_dir = str(app_dir)
    provider = provider or detect_provider(app_dir)

    # A dry run renders the plan and touches nothing — before the CF safety net, which
    # would otherwise harden (mutate) the app.
    if dry_run:
        return _dry_run_plan(app_dir, provider, require_provenance)

    # Nothing may mutate the app between attestation and deploy.
    if not _settle_before_attesting(app_dir, provider):
        return False, None

    proceed, lines = _provenance_gate(app_dir, require_provenance)
    for ln in lines:
        print(ln)
    if not proceed:
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
