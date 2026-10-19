"""area.runner — the runner (data plane, ADR 0002). Runs on the USER's own infra:
dials OUT to a coordinator, receives typed jobs, and executes them locally via
the `area` CLI, streaming logs back. The user's Claude + deploy creds stay here;
nothing but AREA's own commands ever runs.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from area.net.protocol import (
    decode, encode, hello_msg, is_valid_job, job_argv, log_msg, status_msg,
)

ROOT = Path(__file__).resolve().parent.parent


def _area_cmd() -> list[str]:
    """How to invoke the `area` CLI from inside the runner process."""
    return [sys.executable, "-m", "area.cli"]


def _env() -> dict:
    e = dict(os.environ)
    e.setdefault("npm_config_cache", str(Path.home() / ".cache" / "npm-area"))
    e["OPENHANDS_SUPPRESS_BANNER"] = "1"
    e["PYTHONUNBUFFERED"] = "1"
    return e


async def _exec_job(ws, job: dict) -> None:
    jid = job["id"]
    try:
        argv = job_argv(job["kind"], job.get("params"))
    except ValueError as e:
        await ws.send(encode(status_msg(jid, "failed", None)))
        await ws.send(encode(log_msg(jid, f"[runner] bad job: {e}")))
        return
    await ws.send(encode(status_msg(jid, "running")))
    proc = await asyncio.create_subprocess_exec(
        *_area_cmd(), *argv, cwd=str(ROOT), env=_env(),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    assert proc.stdout is not None
    async for raw in proc.stdout:
        await ws.send(encode(log_msg(jid, raw.decode(errors="ignore").rstrip("\n"))))
    rc = await proc.wait()
    await ws.send(encode(status_msg(jid, "done" if rc == 0 else "failed", rc)))


async def _run(coord_url: str, token: str | None) -> None:
    import websockets

    url = coord_url.rstrip("/") + "/ws/runner"
    print(f"[runner] connecting to {url} …", flush=True)
    async with websockets.connect(url, max_size=None) as ws:
        await ws.send(encode(hello_msg("runner", token)))
        print("[runner] connected — waiting for jobs (Ctrl-C to stop)", flush=True)
        async for raw in ws:
            msg = decode(raw)
            if is_valid_job(msg):
                print(f"[runner] job {msg.get('id')} · {msg.get('kind')}", flush=True)
                await _exec_job(ws, msg)


def run_runner(coord_url: str, token: str | None = None) -> int:
    try:
        asyncio.run(_run(coord_url, token))
        return 0
    except KeyboardInterrupt:
        print("\n[runner] stopped.", flush=True)
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"[runner] connection error: {e}", flush=True)
        return 1
