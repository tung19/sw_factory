"""area.wording_probe — the CHEAP gate in front of `area evals`.

Editing an AREA skill or agent prompt changes how the factory behaves, so the spine
applies: never let the same reasoning write AND grade. `area evals` is the expensive
outcome gate (matched-pair runs, ~$71/baseline) and it cannot see the one thing a
wording edit lives or dies by — whether the words actually BIND an agent under pressure.
The `authoring-area-skills` skill runs that cheap behavioral probe natively (the Task
tool, no engine); this module records its verdict and lets you read, per kind, whether
the CURRENT version of a prompt/skill has been probed.

The attestation is keyed to the profile's `digest`, so it is invalidated automatically
the next time that prompt/skill changes — a stale "binds" from a previous wording cannot
vouch for the new one.

Engine-free on purpose (stdlib + area.profile + area.paths): the cheap gate must never
load `area/engine` / the vendored agent SDK. The ledger lives beside obs's, at
`WORKSPACE/.area/wording-probes.jsonl`, and is read-only here except for `record`.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Literal, Optional, cast

from area.paths import WORKSPACE

Verdict = Literal["binds", "weak"]
Status = Literal["recorded", "weak", "missing"]


def _ledger() -> Path:
    # Computed at call time so tests can monkeypatch `area.wording_probe.WORKSPACE`.
    return WORKSPACE / ".area" / "wording-probes.jsonl"


def record(kind: str, digest: str, verdict: Verdict, evidence: str,
           *, reps: int = 0) -> dict[str, Any]:
    """Append one attestation that `kind` at `digest` was wording-probed. Returns the row."""
    row: dict[str, Any] = {
        "kind": kind, "digest": digest, "verdict": verdict,
        "reps": reps, "evidence": evidence, "at": time.time(),
    }
    p = _ledger()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def _all() -> list[dict[str, Any]]:
    p = _ledger()
    if not p.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue  # a torn line never hides the gate; it just isn't an attestation
        if isinstance(row, dict) and "kind" in row and "digest" in row:
            out.append(cast("dict[str, Any]", row))
    return out


def latest_for(kind: str, digest: str) -> Optional[dict[str, Any]]:
    """The most recently recorded probe for exactly this (kind, digest), or None."""
    best: Optional[dict[str, Any]] = None
    for row in _all():
        if row.get("kind") == kind and row.get("digest") == digest:
            if best is None or float(row.get("at", 0)) >= float(best.get("at", 0)):
                best = row
    return best


def status_for(kind: str, digest: str) -> Status:
    row = latest_for(kind, digest)
    if row is None:
        return "missing"
    return "recorded" if row.get("verdict") == "binds" else "weak"


def current_digest(kind: str, *, root: Optional[Path] = None) -> Optional[str]:
    """The digest of `kind`'s CURRENT profile, or None if it has no profile."""
    from area.profile import load_profile  # engine-free; imported lazily

    try:
        prof = load_profile(kind, root=root)
    except Exception:
        return None
    return prof.digest if prof is not None else None


def status_of_kind(kind: str, *, root: Optional[Path] = None) -> Status:
    """Probe status for the kind's CURRENT version (looks the digest up for you)."""
    dg = current_digest(kind, root=root)
    if dg is None:
        return "missing"
    return status_for(kind, dg)


_ICON = {"recorded": "✅", "weak": "⚠", "missing": "·"}


def report(kinds: Optional[list[str]] = None, *, root: Optional[Path] = None) -> str:
    """One line per kind: whether its CURRENT version carries a wording-probe.

    Read this before spending on `area evals`: a `missing`/`weak` kind whose prompt you
    just edited should get the cheap probe (see the `authoring-area-skills` skill) before
    the dear outcome gate runs.
    """
    from area.profile import all_profiles

    names = kinds or sorted(all_profiles(root=root))
    lines: list[str] = []
    for k in names:
        st = status_of_kind(k, root=root)
        row = latest_for(k, current_digest(k, root=root) or "")
        note = ""
        if row is not None:
            note = f"reps={row.get('reps', 0)} — {str(row.get('evidence', ''))[:80]}"
        elif st == "missing":
            note = "no probe for the current version — run the cheap wording test first"
        lines.append(f"  {_ICON.get(st, ' ')} {k:24s} {st:9s} {note}")
    return "\n".join(lines)
