"""area.preview — after a green build, START the app and OPEN it in the browser.

The reality loop (#4) tells the user how to preview; this goes one step further and
actually shows it, because "see it running" is the fastest way to catch a wrong guess
from an unclear requirement. A deployed app opens its live URL; a local build spins up
`npm run dev` on a free port, waits until the port answers, then opens the browser.

Guarded so it only fires for a REAL built app (has package.json with a dev/start
script) — a test/fake app dir is a no-op — and is switched off by --no-open or
AREA_NO_PREVIEW=1. The dev server is detached (survives `area run` exiting) so the
user can keep clicking; its pid is printed so they can stop it.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import webbrowser
from pathlib import Path
from typing import Any, Callable, Optional


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port: int = s.getsockname()[1]
    s.close()
    return port


def _port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def _has_runnable_app(app_dir: Path) -> bool:
    """True only for a real built app: a package.json with a dev or start script."""
    pj = app_dir / "package.json"
    if not pj.is_file():
        return False
    try:
        scripts = json.loads(pj.read_text()).get("scripts") or {}
    except Exception:
        return False
    return "dev" in scripts or "start" in scripts


def open_preview(
    app_dir: str | Path,
    *,
    deployed_url: Optional[str] = None,
    want_open: bool = True,
    timeout: float = 40.0,
    opener: Callable[[str], object] = webbrowser.open,
    spawn: Optional[Callable[[], object]] = None,
    is_ready: Optional[Callable[[], bool]] = None,
) -> dict[str, Any]:
    """Open the built app for the user to verify. Returns a result dict describing
    what happened (never raises). `opener`/`spawn`/`is_ready` are injection seams for
    tests; by default it opens the real browser and spawns `npm run dev`."""
    if not want_open or os.getenv("AREA_NO_PREVIEW"):
        return {"opened": False, "reason": "disabled"}

    if deployed_url:
        try:
            opener(deployed_url)
        except Exception as e:  # noqa: BLE001
            return {"opened": False, "reason": f"opener failed: {e}"}
        print(f"[area] preview: opened live app → {deployed_url}")
        return {"opened": True, "url": deployed_url, "server": False}

    app_dir = Path(app_dir)
    if not _has_runnable_app(app_dir):
        return {"opened": False, "reason": "no runnable app (package.json dev/start)"}

    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    if spawn is None:
        env = {**os.environ,
               "npm_config_cache": os.path.expanduser("~/.cache/npm-area")}

        def spawn() -> subprocess.Popen[bytes]:  # detached dev server; survives this process exiting
            return subprocess.Popen(
                ["npm", "run", "dev", "--", "-p", str(port)],
                cwd=str(app_dir), env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )

    try:
        proc = spawn()
    except Exception as e:  # noqa: BLE001
        return {"opened": False, "reason": f"could not start dev server: {e}"}

    ready = is_ready or (lambda: _port_open(port))
    deadline = time.time() + timeout
    while time.time() < deadline:
        if ready():
            break
        time.sleep(0.5)
    try:
        opener(url)
    except Exception:  # noqa: BLE001 — the server is up; opener is best-effort
        pass
    pid = getattr(proc, "pid", None)
    print(f"[area] preview: {url} is live — opened your browser "
          f"(dev server pid {pid}; stop it with: kill {pid})")
    return {"opened": True, "url": url, "server": True, "pid": pid}
