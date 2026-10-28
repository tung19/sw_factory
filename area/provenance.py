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

from area.paths import GENERATED_AT_ROOT, GENERATED_DIRS
from area.memory import LESSON_FILE
from typing import Any, Optional

PROV_REL = ".area/provenance.json"

# Dirs excluded from the artifact digest so reinstalling deps / rebuilding / writing
# the provenance file doesn't churn it. Split by scope to avoid a blind spot:
#  - _SKIP_ANYWHERE: never app source (deps, VCS, tool + framework build caches) —
#    skipped at ANY depth (a nested node_modules etc. is still vendor junk).
#  - _SKIP_TOPLEVEL: build-OUTPUT names that are ALSO plausible source dir names
#    (`build/`, `dist/`, …) — skipped ONLY at the app root, so a legitimate source
#    file like `src/build/helpers.ts` is still digested (was silently excluded).
# One source of truth, from `area.paths` — this list used to be local and was missing
# `.visual/`, `coverage/`, `out/` and `.turbo/`, all of which the rest of AREA already
# treated as generated. So the attestation could be broken by re-reading a visual score
# or by running the test suite. See GENERATED_DIRS for the full account.
_SKIP_ANYWHERE = set(GENERATED_DIRS)
_SKIP_TOPLEVEL = set(GENERATED_AT_ROOT)
# FILES that the toolchain generates or the running app writes. They are not authored
# source, so digesting them makes the attestation describe a moment rather than an
# artifact — and it broke for real: on 2026-10-28 provenance for `expenses` was written
# at 09:13:39 and AREA's own `npm run dev` preview regenerated `next-env.d.ts` at
# 09:13:40, so the attested digest no longer matched the app one second after it was
# taken, and `area deploy` would have refused a build nothing had tampered with. The
# same would happen to ANY app that persists data the moment a human clicked through
# the preview and saved a row.
#
# Excluding them does not weaken tamper detection: every authored file is still
# digested, and these are regenerated from the authored ones (or are runtime state
# that no deploy should carry). The list is explicit rather than a pattern like
# "anything .d.ts", so adding to it stays a reviewable decision.
# Bumped whenever the set of digested files changes. Without it, widening the
# exclusions above turns every previously VALID attestation into "the artifact digest
# CHANGED since it was gated" — which reads as tampering when the truth is that the
# question changed. A verifier that reports the wrong reason is the defect class this
# audit keeps finding, so the version is recorded and compared.
#   1 — directories only (node_modules, .next, dist, …)
#   2 — also excludes toolchain-generated and runtime-written FILES (M12)
DIGEST_VERSION = 2

_SKIP_FILES = {"next-env.d.ts", ".eslintcache", ".DS_Store", "Thumbs.db",
               LESSON_FILE}  # agent scratch note — must never enter the digest (B9)
_SKIP_SUFFIXES = (
    ".tsbuildinfo", ".log",
    ".db", ".db-journal", ".db-wal", ".db-shm",
    ".sqlite", ".sqlite3",
)


def _iter_source_files(app: Path) -> Iterator[tuple[Path, Path]]:
    for p in sorted(app.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(app)
        if any(part in _SKIP_ANYWHERE for part in rel.parts):
            continue
        if rel.parts and rel.parts[0] in _SKIP_TOPLEVEL:
            continue
        if p.name in _SKIP_FILES or p.name.endswith(_SKIP_SUFFIXES):
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
    """Digest of the skills pack `area/skills.py` installs into a built app — i.e.
    WHICH prompt/domain-knowledge content shaped this build. None if absent.

    Covers the WHOLE pack on purpose, including skills scoped to other targets, and
    must keep doing so: a version answers "what can change this kind" (and is
    therefore scoped — see `area.profile.profile_digest`), while an attestation
    answers "what shaped this build". Narrowing this would make provenance claim
    less than the truth.

    Takes the directory from `area.skills` rather than re-deriving `REPO / "skills"`,
    so there is one answer to where the pack lives.
    """
    from area.skills import SKILLS_DIR as d
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



def _oracle_strength(app: Path, spec_dir: Optional[str | Path]) -> dict[str, Any]:
    """Which acceptance criteria the locked suite can actually SETTLE.

    "Oracle green" is not one fact. A criterion declaring a runtime property whose
    test only greps source reports PASS without checking anything — `expenses` AC-14
    did exactly that while telemetry was enabled. Independence was attested here from
    the start; strength was not recorded at all, so a reader could not tell a strong
    green from a decorative one. Reported, never blocking: an approximating oracle is
    legitimate when it is labelled, and `--strict` is where it blocks (in the
    authoring oracle, so the loop converges on it rather than being told afterwards).
    """
    try:
        import yaml

        from area.verify.strength import classify, unstated, weak

        sd = Path(spec_dir) if spec_dir else None
        acc = (sd / "acceptance.yaml") if sd else None
        hold = app / "__tests__" / "_holdout"
        if not (acc and acc.exists() and hold.is_dir()):
            return {}
        data = yaml.safe_load(acc.read_text()) or {}
        crit = [c for c in (data.get("criteria") or []) if isinstance(c, dict)]
        text = "\n".join(f.read_text(errors="ignore")
                          for f in sorted(hold.glob("*.ts")))
        v = classify(crit, text)
        return {"criteria": len(v), "unableToVerify": weak(v),
                "methodUnstated": unstated(v)}
    except Exception:  # noqa: BLE001 — bookkeeping must never fail an attestation
        return {}

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
        "oracle": _oracle_strength(app, spec_dir),
        "product": {"artifactDigest": artifact_digest(app),
                    "digestVersion": DIGEST_VERSION},
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
      * "absent"   — no provenance recorded (app never gated through AREA),
      * "stale-digest" — recorded under an older digest DEFINITION, so the
        two numbers answer different questions. Fails closed like a mismatch,
        but must not be reported as drift.
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
    ver = (prov.get("product") or {}).get("digestVersion", 1)
    if ver != DIGEST_VERSION:
        # Still fails closed — an unverifiable attestation is not a pass — but the
        # operator is told what actually happened instead of being accused of drift.
        return "stale-digest", (
            f"provenance was recorded under digest definition v{ver}; this AREA "
            f"computes v{DIGEST_VERSION}, so the two numbers are not comparable and "
            "this cannot be treated as gated. Re-gate the app to attest it under the "
            "current definition.\n"
            f"  recorded (v{ver}): {recorded}\n"
            f"  current  (v{DIGEST_VERSION}): {current}"
        )
    return "mismatch", (
        "artifact digest CHANGED since it was gated — refusing to treat it as gated.\n"
        f"  recorded: {recorded}\n  current : {current}"
    )
