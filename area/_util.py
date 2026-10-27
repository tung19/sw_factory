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
