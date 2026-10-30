"""area.engine_util — the engine's STDLIB-ONLY helpers, importing no OpenHands.

ADR 0004 Stage 0. These were defined in `area/engine/adapter.py`, which imports the (30M)
vendored OpenHands SDK at module load. Several modules only need these helpers — the
`Backend` type, `scrubbed_env`, the `Verifier` contract, and the command verifier — yet
importing them through `area.engine` pulled the whole SDK in transitively. Living here, they
import WITHOUT loading OpenHands, so e.g. `import area.verify.nfr` no longer drags the agent
SDK along. There is an import-graph test (tests/test_engine_util_leaf.py) that pins this.

`area.engine` re-exports everything here, so `from area.engine import Backend` still works for
the agent-side modules; the gates and the pipeline import from `area.engine_util` directly.
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Optional, Sequence

from area._util import cmd_timeout, kill_process_group

Backend = Literal["acp", "llm"]


@dataclass
class VerifyResult:
    """Outcome of an acceptance check: ok + human/agent-readable feedback."""

    ok: bool
    feedback: str = ""


Verifier = Callable[[], VerifyResult]


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


def _cmd_timeout() -> float:
    return cmd_timeout()


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
