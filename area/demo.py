"""area.demo — run a committed example app locally, KEYLESS (no Claude, no cost).

The point: let anyone SEE what the factory produces, working, in minutes — without
an LLM key or a cent. It installs deps (once), builds, serves a pre-built example
under examples/<name> on a free port, and opens the browser.
"""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import time
import urllib.request
import webbrowser
from pathlib import Path

from area.paths import REPO

EXAMPLES = REPO / "examples"


def list_examples() -> list[str]:
    if not EXAMPLES.is_dir():
        return []
    return sorted(d.name for d in EXAMPLES.iterdir()
                  if d.is_dir() and (d / "package.json").exists())


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])
    finally:
        s.close()


def _wait_ready(url: str, timeout: float = 60.0) -> bool:
    import urllib.error

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                r.read(32)
            return True
        except urllib.error.HTTPError:
            return True  # server responded (even a 4xx/5xx) → it's up
        except Exception:  # noqa: BLE001 (connection refused / reset → keep waiting)
            time.sleep(0.4)
    return False


def run_demo(name: str, *, open_browser: bool = True, build: bool = True) -> int:
    app = EXAMPLES / name
    if not (app / "package.json").exists():
        avail = ", ".join(list_examples()) or "(none committed)"
        print(f"[area] no example '{name}'. Available: {avail}")
        return 1

    env = dict(os.environ)
    env.setdefault("npm_config_cache", str(Path.home() / ".cache" / "npm-area"))
    port = _free_port()
    env["PORT"] = str(port)

    def sh(cmd: str):
        return subprocess.run(["bash", "-lc", f"{cmd} 2>&1"], cwd=str(app), env=env)

    if not (app / "node_modules").is_dir():
        print(f"[area] demo {name}: installing dependencies (one-time)…")
        if sh("npm install --no-audit --no-fund").returncode != 0:
            print("[area] demo: npm install failed")
            return 1
    if build:
        print(f"[area] demo {name}: building…")
        if sh("npm run build").returncode != 0:
            print("[area] demo: build failed")
            return 1

    url = f"http://localhost:{port}"
    print(f"[area] demo {name}: starting at {url} …")
    proc = subprocess.Popen(["bash", "-lc", "npm run start 2>&1"], cwd=str(app),
                            env=env, start_new_session=True)
    try:
        if _wait_ready(url):
            print(f"[area] ▶ {name} is running at {url}   (Ctrl-C to stop)")
            if open_browser:
                try:
                    webbrowser.open(url)
                except Exception:  # noqa: BLE001
                    pass
        else:
            print("[area] demo: server did not become ready")
        proc.wait()
    except KeyboardInterrupt:
        print("\n[area] demo: stopping…")
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:  # noqa: BLE001
            pass
    return 0
