"""area.evidence — one correlated audit trail per app (PR8 Phase 3).

Construction events (build green, each gate, provenance, deploy) are emitted
into the app's spec-dir `aidlc_trace.jsonl` under the SAME trace_id the Inception
run started, so the whole chain — Inception artifacts → spec → locked oracle →
gates → provenance → deploy — is one auditable trail. `read_trail()` merges the
Inception sub-trail and the spec-dir trail in time order for a view.

Best-effort throughout: emitting evidence must never break a build.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Optional

from area._util import safe_name


def _spec_dir(name: str) -> Path:
    from area.pipeline import WORKSPACE  # lazy: keep this module light / cycle-free

    return WORKSPACE / "specs" / safe_name(name)


def trail_path(name: str) -> Path:
    return _spec_dir(name) / "aidlc_trace.jsonl"


def _inception_trail(name: str) -> Path:
    return _spec_dir(name) / "inception" / "aidlc_trace.jsonl"


def _last_trace(p: Path) -> Optional[str]:
    if not p.exists():
        return None
    for line in reversed(p.read_text(errors="ignore").splitlines()):
        try:
            t: Optional[str] = json.loads(line).get("trace")
            if t:
                return t
        except Exception:  # noqa: BLE001
            pass
    return None


def current_trace(name: str) -> str:
    """The trace to correlate Construction events to: the Inception run's origin
    trace if there was one, else the spec-dir trail's, else a fresh id."""
    for p in (_inception_trail(name), trail_path(name)):
        t = _last_trace(p)
        if t:
            return t
    return "aidlc-" + uuid.uuid4().hex[:12]


def emit(name: str, event: str, data: Optional[dict[str, Any]] = None) -> None:
    """Append one Construction-evidence record to the app's spec-dir trail."""
    try:
        from area.intake.aidlc import emit_evidence

        emit_evidence(_spec_dir(name), current_trace(name), event, data)
    except Exception:  # noqa: BLE001
        pass


def read_trail(name: str, *, trace: Optional[str] = None) -> list[dict[str, Any]]:
    """The ordered audit chain for ONE run of an app: the Inception sub-trail +
    the spec-dir trail, filtered to a single trace_id and merged in order.

    `trace` defaults to the app's CURRENT trace (the latest run) — so after an
    `iterate` (which starts fresh builds) the view shows that run's chain, not
    every historical build's events concatenated. Pass an explicit `trace` to
    inspect an older run. Ordering is (ts, append-index) so equal-timestamp or
    clock-skewed events keep a stable, file-order tiebreak instead of sorting
    ambiguously.
    """
    want = trace or current_trace(name)
    indexed: list[tuple[float, int, dict[str, Any]]] = []
    i = 0
    for p in (_inception_trail(name), trail_path(name)):
        if p.exists():
            for line in p.read_text(errors="ignore").splitlines():
                try:
                    rec = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                if rec.get("trace") == want:
                    indexed.append((float(rec.get("ts", 0) or 0), i, rec))
                    i += 1
    indexed.sort(key=lambda t: (t[0], t[1]))
    return [rec for _, _, rec in indexed]
