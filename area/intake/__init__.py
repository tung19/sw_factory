"""area.intake — ingest external front-end artifacts into AREA's spec.

The Hybrid seam (PLAN §1 decision log): AI-DLC is the governed process
front-end; AREA is the autonomous engine. They join at the FILE boundary here,
not by wiring runtimes together.
"""
from area.intake.aidlc import (
    emit_evidence,
    load_aidlc_artifacts,
    new_trace_id,
    spec_from_aidlc,
)

__all__ = [
    "spec_from_aidlc",
    "load_aidlc_artifacts",
    "new_trace_id",
    "emit_evidence",
]
