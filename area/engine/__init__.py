"""area.engine — adapter over the pinned OpenHands SDK.

Keep all direct SDK imports inside this package so engine churn stays contained. The
stdlib-only helpers now live in `area.engine_util` (ADR 0004 Stage 0, which imports no
OpenHands); they are re-exported here so `from area.engine import Backend` still works for
the agent-side modules, while the gates and the pipeline import them from `area.engine_util`
directly and so never load the SDK.
"""
from area.engine.adapter import (
    ask_cli,
    build_agent,
    mcp_stdio_server,
    run_goal_judged,
    run_once,
    run_until,
)
from area.engine_util import (
    Backend,
    VerifyResult,
    Verifier,
    command_verifier,
    pytest_verifier,
    scrubbed_env,
)

__all__ = [
    "Backend",
    "VerifyResult",
    "scrubbed_env",
    "Verifier",
    "ask_cli",
    "build_agent",
    "mcp_stdio_server",
    "command_verifier",
    "pytest_verifier",
    "run_goal_judged",
    "run_once",
    "run_until",
]
