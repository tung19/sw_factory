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


def handle_control(msg: dict) -> dict | None:
    """Non-job control messages the runner answers locally from its OWN state:
    `chat` (routed through the governed, keyless chat box) and `apps` (the apps in
    this runner's workspace). Returns a reply dict, or None if not a control msg."""
    t = msg.get("type")
    if t == "chat":
        from area.web.chat import route as chat_route

        r = chat_route(str(msg.get("message", "")), str(msg.get("app") or ""))
        return {"type": "chat_reply", "id": msg.get("id"), **r}
    if t == "apps":
        from area.web.jobs import list_apps

        return {"type": "apps", "apps": [a["name"] for a in list_apps()]}
    return None


def _area_cmd() -> list[str]:
    """How to invoke the `area` CLI from inside the runner process."""
    return [sys.executable, "-m", "area.cli"]


def _env() -> dict:
    e = dict(os.environ)
    e.setdefault("npm_config_cache", str(Path.home() / ".cache" / "npm-area"))
    e["OPENHANDS_SUPPRESS_BANNER"] = "1"
    e["PYTHONUNBUFFERED"] = "1"
    return e


# Job kinds whose `area` command accepts --backend (acp keyless | llm keyed).
_BACKEND_KINDS = {"run", "clone", "intake", "iterate"}


def job_argv_for(kind: str, params: dict | None) -> list[str]:
    """`area` args for a job, honoring AREA_RUNNER_BACKEND (headless/container
    runners set it to 'llm' with LLM_API_KEY+LLM_MODEL; the default keyless 'acp'
    needs a Claude Code login on the runner)."""
    argv = job_argv(kind, params)
    be = (os.getenv("AREA_RUNNER_BACKEND") or "").strip()
    if be and kind in _BACKEND_KINDS and "--backend" not in argv:
        argv += ["--backend", be]
    return argv


def fold_requirement_doc(params: dict | None) -> tuple[dict, str | None]:
    """If a run job carries an uploaded requirement doc (base64), extract its text
    and fold it into `requirement`. The UI and runner are on different machines, so
    the file rides in the job; the runner extracts here, reusing the same parser the
    local dashboard uses (text formats need no deps; PDF/docx use pypdf/python-docx
    if present, else a clear marker). Returns (params, note_or_None); never raises."""
    p = dict(params or {})
    if not p.get("doc_b64"):
        return p, None
    import base64

    from area.web.upload import parse_file

    doc_name = str(p.pop("doc_name", "document"))
    try:
        text = parse_file(doc_name, base64.b64decode(p.pop("doc_b64"))).strip()
    except Exception as e:  # noqa: BLE001 — never fail a job on doc parsing
        return p, f"doc parse warn: {e}"
    if text:
        base = (p.get("requirement") or "").strip()
        p["requirement"] = f"{base}\n\n=== {doc_name} ===\n{text}".strip()
        return p, f"đọc tài liệu {doc_name}: {len(text)} ký tự"
    return p, None


async def _exec_job(ws, job: dict) -> None:
    jid = job["id"]
    params, note = fold_requirement_doc(job.get("params"))
    if note:
        await ws.send(encode(log_msg(jid, f"[runner] {note}")))
    try:
        argv = job_argv_for(job["kind"], params)
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
    from urllib.parse import quote

    url = coord_url.rstrip("/") + "/ws/runner"
    if token:
        url += "?token=" + quote(token)
    print(f"[runner] connecting to {coord_url.rstrip('/')}/ws/runner …", flush=True)
    async with websockets.connect(url, max_size=None) as ws:
        await ws.send(encode(hello_msg("runner", token)))
        print("[runner] connected — waiting for jobs (Ctrl-C to stop)", flush=True)
        async for raw in ws:
            msg = decode(raw)
            if is_valid_job(msg):
                print(f"[runner] job {msg.get('id')} · {msg.get('kind')}", flush=True)
                await _exec_job(ws, msg)
                continue
            reply = handle_control(msg)
            if reply is not None:
                await ws.send(encode(reply))


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
