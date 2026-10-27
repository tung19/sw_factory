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
keyless: no external signer, but a record tying the product to its inputs, the checks
it passed, and the POLICY it ran under. (Research seam: PLAN SecOps roadmap; the
deterministic verify here is the "hard halt", complementing advisory review.)

HOW TO READ THE `gates` BLOCK (v2) — the record must not claim more than it knows:
  * `ran: false`            → the gate was not selected; nothing was measured.
  * `blocking: true`        → a breach would have failed the build, so a pass here
                              means the gate's own criterion was met.
  * `blocking: false`       → the gate was ADVISORY. `blocked: false` then means only
                              "it did not stop the build" — it does NOT mean the
                              measurement passed. Read the gate's own artifact
                              (e.g. `.visual/score.json`) for the number.
Attestation is NOT tamper-evident in the strong sense: it is written inside the app's
own `.area/` — a tree the build agent can reach — and is unsigned. See
`docs/secure-factory-gap-assessment.md` (items 2, 9).
"""
from __future__ import annotations

import hashlib
import subprocess
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
              "nfr.yaml", "perf.yaml", "cost.yaml", "visual.yaml")


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


def factory_commit() -> str:
    """The FACTORY's own git revision (`<sha>` or `<sha>-dirty`), or "unknown".

    Without this, a past build can't be reproduced: the gates, prompts and thresholds
    that judged it live in AREA itself, not in the app. Fail-soft — a missing git must
    never break a build."""
    from area.paths import REPO

    def _git(*a: str) -> Optional[str]:
        try:
            r = subprocess.run(["git", "-C", str(REPO), *a],
                               capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return None
        return r.stdout.strip() if r.returncode == 0 else None

    sha = _git("rev-parse", "HEAD")
    if not sha:
        return "unknown"
    dirty = _git("status", "--porcelain")
    return sha + ("-dirty" if dirty else "")


def skills_digest() -> Optional[str]:
    """Digest of the skills pack `area/skills.py` installs into every built app — i.e.
    WHICH prompt/domain-knowledge content shaped this build. None if absent."""
    from area.paths import REPO

    d = REPO / "skills"
    if not d.is_dir():
        return None
    h = hashlib.sha256()
    found = False
    for p in sorted(d.rglob("*")):
        if not p.is_file():
            continue
        found = True
        h.update(p.relative_to(d).as_posix().encode())
        h.update(b"\0")
        try:
            h.update(hashlib.sha256(p.read_bytes()).digest())
        except OSError:
            h.update(b"<unreadable>")
    return ("sha256:" + h.hexdigest()) if found else None


def write_provenance(
    app_dir: str | Path,
    *,
    name: str,
    target: str,
    gates: dict[str, Any],
    spec_dir: Optional[str | Path] = None,
    builder: Optional[str] = None,
    policy: Optional[dict[str, Any]] = None,
    gates_not_run: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Record a provenance attestation into <app>/.area/provenance.json.

    `builder` must name what ACTUALLY built this (e.g. "area/acp"); it used to default
    to a literal that was wrong for every non-ACP backend. `policy` records the run's
    own configuration (model, flags, caps, factory revision) so the build can be
    reconstructed. `gates` values may be a bool (v1 callers) or a
    {ran, blocking, blocked} mapping — see the module docstring on how to read it."""
    app = Path(app_dir)
    pol = dict(policy or {})
    pol.setdefault("factoryCommit", factory_commit())
    pol.setdefault("skillsDigest", skills_digest())
    prov = {
        "_type": "area.slsa-like/v2",
        "name": name,
        "builtAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "builder": builder or "area/unknown",
        "target": target,
        "materials": {"spec": spec_digest(spec_dir)},
        "gates": dict(gates),
        "gatesNotRun": sorted(gates_not_run or []),
        "policy": pol,
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


def _gate_summary(gates: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Split a recorded `gates` block into (enforced, advisory) names.

    A plain bool is a v1 record: counted as enforced when true, because v1 had no way
    to express "advisory pass" — that conflation is exactly what v2 fixes."""
    enforced: list[str] = []
    advisory: list[str] = []
    for g, v in (gates or {}).items():
        if isinstance(v, dict):
            if not v.get("ran"):
                continue
            (enforced if v.get("blocking") else advisory).append(str(g))
        elif v:
            enforced.append(str(g))
    return sorted(enforced), sorted(advisory)


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
        enforced, advisory = _gate_summary(prov.get("gates") or {})
        bits = [f"gates enforced: {', '.join(enforced) or '—'}"]
        if advisory:
            bits.append(f"advisory ONLY (not a pass): {', '.join(advisory)}")
        not_run = [str(g) for g in (prov.get("gatesNotRun") or [])]
        if not_run:
            bits.append(f"not run: {', '.join(not_run)}")
        return "ok", f"artifact matches provenance ({current[:23]}…); " + "; ".join(bits)
    return "mismatch", (
        "artifact digest CHANGED since it was gated — refusing to treat it as gated.\n"
        f"  recorded: {recorded}\n  current : {current}"
    )
