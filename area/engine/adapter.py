"""area.engine — thin adapter over the (pinned) OpenHands software-agent-sdk.

Why this module exists:
- One place that knows the SDK API, so SDK churn is contained here (the SDK
  ships weekly, sometimes breaking releases).
- Two agent backends:
    * "acp" -> Claude Code via ACP. Uses your Claude Code login, NO api key.
    * "llm" -> OpenHands-native agent via LiteLLM. Needs LLM_API_KEY + LLM_MODEL.
- A keyless, test-driven self-correct loop (`run_until`): the "oracle" for
  "done" is YOUR acceptance checks passing, not an LLM judge. This is what lets
  the self-correct loop work on the no-key ACP backend. `run_goal_judged` keeps
  the SDK's judge-LLM loop available for when a judge key is present.

Pinned against openhands-sdk 1.55.1. APIs used here were verified against the
installed package, not guessed.
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Optional, Sequence

from openhands.sdk import LLM, Agent, Conversation, Tool
from openhands.sdk.agent import ACPAgent
from openhands.sdk.agent.base import AgentBase
from openhands.sdk.settings.acp_providers import ACP_PROVIDERS
from openhands.tools.file_editor import FileEditorTool
from openhands.tools.task_tracker import TaskTrackerTool
from openhands.tools.terminal import TerminalTool

Backend = Literal["acp", "llm"]

# Default toolset for the native (llm) backend. The ACP backend brings its own
# tools from the Claude Code CLI, so this does not apply there.
_DEFAULT_TOOLS = [TerminalTool, FileEditorTool, TaskTrackerTool]


def _filter_kwargs(cls, kwargs: dict) -> dict:
    """Keep only kwargs that are real model fields and not None.

    Defensive against SDK field renames between pinned bumps.
    """
    fields = getattr(cls, "model_fields", {})
    return {k: v for k, v in kwargs.items() if k in fields and v is not None}


def build_agent(
    backend: Backend = "acp",
    *,
    model: Optional[str] = None,
    mcp_config: Optional[dict] = None,
    acp_provider: str = "claude-code",
) -> AgentBase:
    """Construct an agent.

    - backend="acp": drives the Claude Code CLI via ACP using your existing
      login (no API key). `model` is an ACP model alias (e.g. "sonnet").
    - backend="llm": OpenHands-native agent; needs LLM_API_KEY + LLM_MODEL
      (or pass `model=`).

    `mcp_config` is a dict[str, MCPServer] (e.g. REA, Vercel) wired into the
    agent for both backends.
    """
    if backend == "acp":
        kwargs = {
            "acp_command": list(ACP_PROVIDERS[acp_provider].default_command),
            "acp_model": model,
            "mcp_config": mcp_config,
        }
        return ACPAgent(**_filter_kwargs(ACPAgent, kwargs))

    if backend == "llm":
        api_key = os.getenv("LLM_API_KEY")
        model = model or os.getenv("LLM_MODEL")
        if not api_key or not model:
            raise RuntimeError(
                "llm backend needs LLM_API_KEY and LLM_MODEL (or pass model=)."
            )
        llm = LLM(
            model=model, api_key=api_key, base_url=os.getenv("LLM_BASE_URL") or None
        )
        kwargs = {
            "llm": llm,
            "tools": [Tool(name=t.name) for t in _DEFAULT_TOOLS],
            "mcp_config": mcp_config,
        }
        return Agent(**_filter_kwargs(Agent, kwargs))

    raise ValueError(f"unknown backend: {backend!r}")


@dataclass
class VerifyResult:
    """Outcome of an acceptance check: ok + human/agent-readable feedback."""

    ok: bool
    feedback: str = ""


Verifier = Callable[[], VerifyResult]


def _mk_conversation(agent, ws, agent_iters, budget):
    """Build a Conversation with per-run caps (P2 cost/budget guard).

    agent_iters caps steps per agent.run() (default 80; env AREA_AGENT_ITERS;
    the SDK default is 500). budget caps USD spend per run (env AREA_MAX_BUDGET).
    Budget needs LocalConversation (the Conversation factory omits it).
    """
    if agent_iters is None:
        agent_iters = int(os.getenv("AREA_AGENT_ITERS", "80"))
    if budget is None:
        b = os.getenv("AREA_MAX_BUDGET")
        budget = float(b) if b else None
    if budget is not None:
        try:
            from openhands.sdk.conversation.impl.local_conversation import (
                LocalConversation,
            )

            return LocalConversation(
                agent=agent, workspace=str(ws),
                max_iteration_per_run=agent_iters, max_budget_per_run=budget,
            )
        except Exception:
            pass  # fall back to the factory (iteration cap only)
    return Conversation(
        agent=agent, workspace=str(ws), max_iteration_per_run=agent_iters
    )


def run_once(agent, workspace, message, *, agent_iters=None, budget=None):
    """Send one message and run the agent to completion (capped)."""
    ws = Path(workspace)
    ws.mkdir(parents=True, exist_ok=True)
    conv = _mk_conversation(agent, ws, agent_iters, budget)
    conv.send_message(message)
    conv.run()
    return conv


def run_until(
    agent: AgentBase,
    workspace: str | Path,
    task: str,
    verify: Verifier,
    *,
    max_iters: int = 5,
    agent_iters: int | None = None,
    budget: float | None = None,
) -> tuple[bool, Conversation]:
    """Keyless self-correct loop.

    Run the agent on `task`, then call `verify()`. While it fails, feed the
    check output back and run again, up to `max_iters` times. The oracle is
    `verify` (e.g. your pytest/E2E/build), so this works with the no-key ACP
    backend. Returns (passed, conversation).
    """
    ws = Path(workspace)
    ws.mkdir(parents=True, exist_ok=True)
    conv = _mk_conversation(agent, ws, agent_iters, budget)
    conv.send_message(task)
    conv.run()

    for attempt in range(1, max_iters + 1):
        result = verify()
        if result.ok:
            return True, conv
        conv.send_message(
            "The acceptance checks did not pass yet. Fix the code so they pass.\n\n"
            f"--- check output (attempt {attempt}/{max_iters}) ---\n{result.feedback}"
        )
        conv.run()

    return verify().ok, conv


def command_verifier(cmd: Sequence[str], *, cwd: str | Path | None = None) -> Verifier:
    """A Verifier that runs a shell command; exit code 0 means pass."""

    def _run() -> VerifyResult:
        try:
            proc = subprocess.run(
                list(cmd),
                cwd=str(cwd) if cwd else None,
                capture_output=True,
                text=True,
            )
        except OSError as e:  # missing binary, bad cwd, etc. — never crash the loop
            return VerifyResult(ok=False, feedback=f"verifier command failed: {e}")
        out = (proc.stdout + "\n" + proc.stderr).strip()
        return VerifyResult(ok=proc.returncode == 0, feedback=out[-4000:])

    return _run


def pytest_verifier(test_path: str | Path, *, cwd: str | Path | None = None) -> Verifier:
    """Convenience Verifier: run pytest on `test_path` with the current python."""
    return command_verifier(
        [sys.executable, "-m", "pytest", "-q", str(test_path)], cwd=cwd
    )


def run_goal_judged(
    conversation: Conversation,
    objective: str,
    *,
    judge_model: str,
    max_iterations: int = 10,
):
    """Optional: the SDK's judge-LLM goal loop.

    NOTE: the judge is a real LLM, so this path needs a key (JUDGE_API_KEY or
    LLM_API_KEY). Prefer `run_until` for the keyless ACP path.
    """
    from openhands.sdk.conversation.goal import run_goal

    api_key = os.getenv("JUDGE_API_KEY") or os.getenv("LLM_API_KEY")
    if not api_key:
        raise RuntimeError("run_goal judge needs JUDGE_API_KEY or LLM_API_KEY.")
    judge_llm = LLM(
        model=judge_model, api_key=api_key, base_url=os.getenv("LLM_BASE_URL") or None
    )
    return run_goal(conversation, objective, judge_llm, max_iterations=max_iterations)
