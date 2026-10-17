#!/usr/bin/env python
"""AREA Phase 0 smoke test — confirm the OpenHands SDK engine runs end to end.

Needs an LLM key. Run it like:
    cp config/llm.example.env config/llm.env      # then edit config/llm.env
    set -a && source config/llm.env && set +a
    uv run python scripts/01_hello_world.py

Adapted from the canonical SDK example (vendored at
scripts/_reference/01_hello_world.py). Pinned to openhands-sdk 1.55.1 — keep
real engine usage behind area/engine so SDK churn stays contained.
"""
import os
import sys
from pathlib import Path

from openhands.sdk import LLM, Agent, Conversation, Tool
from openhands.tools.file_editor import FileEditorTool
from openhands.tools.task_tracker import TaskTrackerTool
from openhands.tools.terminal import TerminalTool

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = ROOT / "workspace"

model = os.getenv("LLM_MODEL")
api_key = os.getenv("LLM_API_KEY")
if not api_key or not model:
    sys.exit(
        "Missing LLM config. Set LLM_MODEL and LLM_API_KEY first:\n"
        "  cp config/llm.example.env config/llm.env   # then edit it\n"
        "  set -a && source config/llm.env && set +a\n"
        "  uv run python scripts/01_hello_world.py"
    )

llm = LLM(model=model, api_key=api_key, base_url=os.getenv("LLM_BASE_URL") or None)

agent = Agent(
    llm=llm,
    tools=[
        Tool(name=TerminalTool.name),
        Tool(name=FileEditorTool.name),
        Tool(name=TaskTrackerTool.name),
    ],
)

WORKSPACE.mkdir(exist_ok=True)
conversation = Conversation(agent=agent, workspace=str(WORKSPACE))
conversation.send_message(
    "Write 3 short facts about the AREA project into FACTS.txt "
    "(read ../PLAN.md if you can find it)."
)
conversation.run()
print(f"\n✅ Engine ran. Check {WORKSPACE / 'FACTS.txt'}")
