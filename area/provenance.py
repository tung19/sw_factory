"""area.provenance — SLSA-style build provenance for AREA-generated apps.

After a green build + gates, AREA records a provenance attestation: WHAT spec the
app was built from (materials), WHICH target + gates, and a content digest of the
built app's **SOURCE tree** (product). Before deploy, that digest is re-verified —
so a SOURCE file modified AFTER it was gated, or an app never gated at all, cannot
silently ship.

SCOPE (be honest, don't over-trust): the product digest covers the app's own
source files, NOT the compiled/shipped bundle (`.next`/`.open-next`/`.cloudflare`
etc. are deterministic build outputs, excluded so a rebuild doesn't churn the
digest). So "provenance ok" means *the source that was gated is unchanged*, not
*the exact bytes that ship are byte-for-byte attested*. Attesting the shipped
bundle (and capturing it AFTER the CF `harden_cf_app` mutation) is a deeper change
left for a signed-provenance pass.

This is SLSA-style provenance (materials → build → product) at the logic level and
keyless: no external signer, but a tamper-evident record tying the product to its
inputs and the checks it passed. (Research seam: PLAN SecOps roadmap; the
deterministic verify here is the "hard halt", complementing advisory review.)
"""
from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Optional

PROV_REL = ".area/provenance.json"

# Dirs excluded from the artifact digest so reinstalling deps / rebuilding / writing
# the provenance file doesn't churn it. Split by scope to avoid a blind spot:
#  - _SKIP_ANYWHERE: never app source (deps, VCS, tool + framework build caches) —
#    skipped at ANY depth (a nested node_modules etc. is still vendor junk).
#  - _SKIP_TOPLEVEL: build-OUTPUT names that are ALSO plausible source dir names
#    (`build/`, `dist/`, …) — skipped ONLY at the app root, so a legitimate source
#    file like `src/build/helpers.ts` is still digested (was silently excluded).
_SKIP_ANYWHERE = {
    "node_modules", ".next", ".vinext", ".open-next", ".cloudflare", ".wrangler",
    ".openhands", ".git", ".vercel", ".area", ".claude",
}
_SKIP_TOPLEVEL = {"dist", "build", "test-results", "playwright-report"}


def _iter_source_files(app: Path) -> Iterator[tuple[Path, Path]]:
    for p in sorted(app.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(app)
        if any(part in _SKIP_ANYWHERE for part in rel.parts):
            continue
        if rel.parts and rel.parts[0] in _SKIP_TOPLEVEL:
            continue
        yield rel, p


def artifact_digest(app_dir: str | Path) -> str:
    """Deterministic sha256 over the app's own source (path + bytes of each file).
    A changed, added, or removed source file changes the digest."""
    app = Path(app_dir)
    h = hashlib.sha256()
    for rel, p in _iter_source_files(app):
        h.update(rel.as_posix().encode())
        h.update(b"\0")
        try:
            h.update(hashlib.sha256(p.read_bytes()).digest())
        except OSError:
            h.update(b"<unreadable>")
    return "sha256:" + h.hexdigest()


# All spec-dir materials the build + gates actually consumed — so the attestation
# covers the oracle (acceptance), the assumptions ledger the clarify gate used, and
# the budgets the nfr/perf/cost gates enforced, not just the base spec.
_MATERIALS = ("spec.yaml", "acceptance.yaml", "assumptions.yaml",
              "nfr.yaml", "perf.yaml", "cost.yaml")


def spec_digest(spec_dir: Optional[str | Path]) -> Optional[str]:
    """Digest of the spec materials the build/gates used (spec + acceptance +
    assumptions + nfr/perf/cost budgets). None if none are present."""
    if not spec_dir:
        return None
    sd = Path(spec_dir)
    h = hashlib.sha256()
    found = False
    for fn in _MATERIALS:
        p = sd / fn
        if p.exists():
            found = True
            h.update(fn.encode())
            h.update(b"\0")
            h.update(p.read_bytes())
    return ("sha256:" + h.hexdigest()) if found else None


def write_provenance(
    app_dir: str | Path,
    *,
    name: str,
    target: str,
    gates: dict[str, bool],
    spec_dir: Optional[str | Path] = None,
    builder: str = "area/openhands-acp",
) -> dict[str, Any]:
    """Record a provenance attestation into <app>/.area/provenance.json."""
    app = Path(app_dir)
    prov = {
        "_type": "area.slsa-like/v1",
        "name": name,
        "builtAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "builder": builder,
        "target": target,
        "materials": {"spec": spec_digest(spec_dir)},
        "gates": dict(gates),
        "product": {"artifactDigest": artifact_digest(app)},
    }
    out = app / PROV_REL
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(prov, indent=2))
    return prov


def read_provenance(app_dir: str | Path) -> Optional[dict[str, Any]]:
    p = Path(app_dir) / PROV_REL
    if not p.exists():
        return None
    try:
        data: dict[str, Any] = json.loads(p.read_text())
        return data
    except (OSError, json.JSONDecodeError):
        return None


def verify_provenance(app_dir: str | Path) -> tuple[str, str]:
    """Re-verify the built artifact against its recorded provenance.

    Returns (status, detail) where status is:
      * "ok"       — digest matches the gated artifact,
      * "mismatch" — the source changed since gating (tamper/drift) → block deploy,
      * "absent"   — no provenance recorded (app never gated through AREA).
    """
    prov = read_provenance(app_dir)
    if not prov:
        return "absent", "no provenance recorded (app not gated through AREA)"
    recorded = (prov.get("product") or {}).get("artifactDigest")
    current = artifact_digest(app_dir)
    if recorded == current:
        passed = [g for g, v in (prov.get("gates") or {}).items() if v]
        return "ok", f"artifact matches provenance ({current[:23]}…); gates passed: {passed or '—'}"
    return "mismatch", (
        "artifact digest CHANGED since it was gated — refusing to treat it as gated.\n"
        f"  recorded: {recorded}\n  current : {current}"
    )
