"""area.inception — AI-DLC Inception front-end (PR8 Phase 1).

A governed flow that turns a raw requirement into contract-compliant Inception
artifacts (docs/aidlc-artifact-contract.md) through human-approved bolts:
intent -> user stories -> Units of Work -> Testing Posture. The AI proposes each
bolt, the human disposes (accept / edit / regenerate); every bolt emits evidence
under one trace_id. The output feeds area.intake.aidlc unchanged.
"""
from area.inception.engine import BOLTS, run_inception, validate_artifacts

__all__ = ["BOLTS", "run_inception", "validate_artifacts"]
