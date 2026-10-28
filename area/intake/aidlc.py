"""area.intake.aidlc — the Hybrid seam: AI-DLC Inception artifacts -> AREA spec.

AI-DLC (awslabs/aidlc-workflows) runs as the GOVERNED FRONT-END (requirements,
user stories, Units of Work, Testing Posture) and emits artifacts. We do NOT
port its TypeScript engine (that would destroy the community/bus-factor and
can't carry its harness-neutrality anyway). We INGEST its artifacts at the FILE
boundary and translate them into AREA's spec.yaml + acceptance.yaml; then AREA's
autonomous engine (--tdd, chaos, deploy) takes over.

For end-to-end audit, Construction evidence is EMITTED back as a correlated
trace (aidlc_trace.jsonl) so AI-DLC's own audit trail stays the system of
record — we emit into it, we don't reimplement it.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from area.engine import Backend, build_agent, run_until
from area.spec.extract import _SCHEMA_GUIDE, _spec_verifier, expected_block
from area import screen
from area.spec.models import Acceptance, Spec, load_acceptance, load_spec

_ARTIFACT_EXTS = {".md", ".markdown", ".txt", ".yaml", ".yml", ".json"}
_MAX_CHARS = 60_000


def load_aidlc_artifacts(path: str | Path, *, max_chars: int = _MAX_CHARS) -> str:
    """Read AI-DLC artifact file(s) into one bounded text blob for translation.

    `path` may be a single file or a directory (read recursively, sorted). Only
    text-ish artifacts are included; the blob is capped at `max_chars`.
    """
    p = Path(path)
    if not p.exists():
        raise RuntimeError(f"no AI-DLC artifacts at {p}")
    files = (
        [p]
        if p.is_file()
        else sorted(
            f for f in p.rglob("*")
            if f.is_file() and f.suffix.lower() in _ARTIFACT_EXTS
        )
    )
    if not files:
        raise RuntimeError(f"no AI-DLC artifact files (.md/.yaml/.json/...) under {p}")
    parts: list[str] = []
    total = 0
    for f in files:
        try:
            text = f.read_text(errors="ignore")
        except OSError:
            continue
        rel = f.name if p.is_file() else f.relative_to(p)
        block = f"=== {rel} ===\n{text}\n"
        if total + len(block) > max_chars:
            parts.append(block[: max(0, max_chars - total)])
            break
        parts.append(block)
        total += len(block)
    blob = "\n".join(parts).strip()
    if not blob:
        raise RuntimeError(f"AI-DLC artifacts under {p} were empty")
    # The artifacts are untrusted input (they may come from another team's tooling)
    # and this blob is handed straight to an agent.
    blob, found = screen.redact_text(blob)
    if found:
        print(screen.format_report([(str(p), f) for f in found],
                                   what="the AI-DLC artifacts"))
    return blob


def new_trace_id() -> str:
    """A correlation id tying AREA's Construction evidence to AI-DLC's trail."""
    return "aidlc-" + uuid.uuid4().hex[:12]


def emit_evidence(
    spec_dir: str | Path, trace_id: str, event: str, data: Optional[dict[str, Any]] = None
) -> None:
    """Append one Construction-evidence record (emit into AI-DLC's audit trail).

    Never raises — evidence is best-effort and must not break a build.
    """
    rec = {"ts": time.time(), "trace": trace_id, "event": event, "data": data or {}}
    trail = Path(spec_dir) / "aidlc_trace.jsonl"
    try:
        trail.parent.mkdir(parents=True, exist_ok=True)
        with trail.open("a") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError:
        pass


def spec_from_aidlc(
    artifacts: str | Path,
    out_dir: str | Path,
    *,
    expected: Optional[str] = None,
    backend: Backend = "acp",
    model: Optional[str] = None,
    max_iters: int = 3,
    trace_id: Optional[str] = None,
    reuse: bool = False,
) -> tuple[Spec, Acceptance]:
    """Translate AI-DLC Inception artifacts into a validated AREA spec artifact.

    Same output schema as area.spec, so it flows into the exact same build/TDD/
    deploy pipeline. The AI-DLC Testing Posture becomes acceptance criteria.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    if reuse:
        sp, ac = out / "spec.yaml", out / "acceptance.yaml"
        if not (sp.exists() and ac.exists()):
            raise RuntimeError(
                f"--use-spec: no spec to reuse at {out}. Run without it first.")
        print(f"[area] intake : reusing {sp} (not re-translating the artifacts)")
        return load_spec(sp), load_acceptance(ac)
    trace_id = trace_id or new_trace_id()
    blob = load_aidlc_artifacts(artifacts)
    emit_evidence(out, trace_id, "intake.start", {"artifacts": str(artifacts)})

    task = (
        "You are the INTAKE ADAPTER of a software factory. Translate the AI-DLC "
        "Inception artifacts below (requirements, user stories, Units of Work, "
        "and especially the Testing Posture / acceptance intent) into our "
        "structured spec. Be faithful: carry EVERY unit of work over as a "
        "feature and EVERY testing-posture statement as an acceptance criterion. "
        "Do NOT invent scope beyond the artifacts.\n\n"
        f"=== AI-DLC ARTIFACTS ===\n{blob}\n\n"
        f"{expected_block(expected)}=== OUTPUT FORMAT ===\n{_SCHEMA_GUIDE}"
    )
    agent = build_agent(backend, model=model)
    try:
        passed, _ = run_until(
            agent, out, task, _spec_verifier(out),
            max_iters=max_iters, label="intake:aidlc",
        )
    finally:
        agent.close()

    if not passed:
        emit_evidence(out, trace_id, "intake.failed")
        raise RuntimeError(
            f"AI-DLC intake did not validate after {max_iters} attempts; inspect {out}"
        )
    emit_evidence(out, trace_id, "intake.spec_ready")
    return load_spec(out / "spec.yaml"), load_acceptance(out / "acceptance.yaml")
