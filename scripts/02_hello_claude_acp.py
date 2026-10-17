#!/usr/bin/env python
"""AREA Phase 0 smoke test (ACP / Claude Code).

Runs the OpenHands engine using your EXISTING Claude Code login instead of a
raw API key. OpenHands' "claude-code" ACP provider authenticates via Claude
Code's own login flow (its metadata has api_key_env_var=None), so no
ANTHROPIC_API_KEY is needed.

Requirements:
  - `claude` CLI logged in (you have it), OR CLAUDE_CODE_OAUTH_TOKEN exported
    from `claude setup-token`.
  - NO stray ANTHROPIC_API_KEY in the env (it takes precedence and would
    bypass the Claude Code login).
  - Node / npx available (used to launch the claude-agent-acp bridge; the npm
    package is fetched on first run).

Run:
    uv run python scripts/02_hello_claude_acp.py

Note: with the ACP path the inner coding loop is Claude Code's own loop. Whether
OpenHands' goal-completion judge (run_goal) wraps an ACP agent is something to
confirm in Phase 1 — this script only verifies the engine runs via your login.
"""
import os
from pathlib import Path

from openhands.sdk.agent import ACPAgent
from openhands.sdk.conversation import Conversation
from openhands.sdk.settings.acp_providers import ACP_PROVIDERS

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = ROOT / "workspace"
WORKSPACE.mkdir(exist_ok=True)

if os.getenv("ANTHROPIC_API_KEY"):
    print(
        "⚠️  ANTHROPIC_API_KEY is set — it takes precedence over your Claude Code "
        "login. Unset it to use the subscription login instead."
    )

# The claude-code provider's default_command launches the claude-agent-acp
# bridge via npx. (Pick a model with acp_model="sonnet"/"claude-opus-5"/... )
agent = ACPAgent(acp_command=list(ACP_PROVIDERS["claude-code"].default_command))

try:
    conversation = Conversation(agent=agent, workspace=str(WORKSPACE))
    conversation.send_message(
        "Write 3 short facts about the AREA project into FACTS.txt."
    )
    conversation.run()
    print(f"\n✅ Engine ran via Claude Code (ACP). Check {WORKSPACE / 'FACTS.txt'}")
finally:
    agent.close()
