"""area.engine — adapter over the pinned OpenHands SDK.

Keep all direct SDK imports inside this package so engine churn stays contained.
"""
from area.engine.adapter import (
    VerifyResult,
    Verifier,
    ask_cli,
    build_agent,
    command_verifier,
    mcp_stdio_server,
    pytest_verifier,
    run_goal_judged,
    run_once,
    run_until,
)

__all__ = [
    "VerifyResult",
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
