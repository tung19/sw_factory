"""Small shared helpers."""
from __future__ import annotations

import os
import re
import signal
import subprocess
from typing import Any


def safe_name(name: str, *, default: str = "app") -> str:
    """Sanitize a project name into a single safe path segment.

    Strips anything but [A-Za-z0-9_-], which removes path separators and dots,
    so a crafted name (e.g. "../../etc") cannot traverse out of workspace/.
    """
    s = re.sub(r"[^A-Za-z0-9_-]", "-", (name or "").strip()).strip("-_")
    return s or default


def kill_process_group(proc: "subprocess.Popen[Any]", *, grace: float = 8.0) -> None:
    """Stop a child AND everything it spawned.

    `proc.terminate()` signals one pid, so an `npm run build` that forked its own
    children leaves them running — which is how a cancelled job keeps burning CPU and
    holding a port. This signals the whole process group, so the child must have been
    started with `start_new_session=True`; without it, killpg would target OUR group,
    hence the getpgid guard and the terminate() fallback.

    Promoted from area.verify.perf._stop, which proved it on real dev servers."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass
    try:
        proc.wait(timeout=grace)
    except Exception:  # noqa: BLE001
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:  # noqa: BLE001
            pass


# ---- one wall clock for "a command that runs the generated project" ----------

CMD_TIMEOUT_DEFAULT = 1800.0


def cmd_timeout() -> float:
    """Seconds a single build/test/provider command may take, from `AREA_CMD_TIMEOUT`.

    Lives here, not in each caller, because there were several of these: the agent
    verifier had one and `cf_scaffold`, `nfr`, `demo` and `export` had none at all, while
    SECURITY.md claimed that "every agent/build/provider subprocess has a wall clock".
    One definition means the claim can be true and stay true. Read at CALL time so a test
    or an operator can change it with an env var; 0 or negative disables it (returns 0.0,
    which callers pass as `timeout=None`).
    """
    import os

    raw = (os.getenv("AREA_CMD_TIMEOUT") or "").strip()
    try:
        v = float(raw) if raw else CMD_TIMEOUT_DEFAULT
    except ValueError:
        return CMD_TIMEOUT_DEFAULT
    return v if v > 0 else 0.0


def cmd_timeout_or_none() -> "float | None":
    """`cmd_timeout()` shaped for `subprocess.run(timeout=...)`: None when disabled."""
    t = cmd_timeout()
    return t if t > 0 else None
