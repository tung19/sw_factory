"""AREA — internal AI software factory.

Orchestrator around the OpenHands software-agent-sdk (execution engine).
See PLAN.md for the full architecture. Submodules:

- intake  : receive requirement (Flow A) or sample app (Flow B)
- re       : reverse-engineer, 2 tiers (browser/repomix | REA MCP, opt-in)
- spec    : spec stage -> spec.yaml + acceptance.yaml + tests/
- engine  : adapter wrapping the (pinned) OpenHands SDK -- contains churn
- verify  : E2E + acceptance + holdout checks
- deploy  : Vercel adapter + human gate
- memory  : experience / learning store
"""

__version__ = "0.0.0"
