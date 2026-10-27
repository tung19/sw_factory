"""area.runner — the runner (data plane, ADR 0002). Runs on the USER's own infra:
dials OUT to a coordinator, receives typed jobs, and executes them locally via
the `area` CLI, streaming logs back. The user's Claude + deploy creds stay here;
nothing but AREA's own commands ever runs.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import asyncio
import os
import sys
from pathlib import Path

from area.net.protocol import (
    decode, encode, hello_msg, is_valid_job, job_argv, log_msg, status_msg,
)

ROOT = Path(__file__).resolve().parent.parent


def handle_control(msg: dict[str, Any]) -> dict[str, Any] | None:
    """Non-job control messages the runner answers locally from its OWN state:
    `chat` (routed through the governed, keyless chat box) and `apps` (the apps in
    this runner's workspace). Returns a reply dict[str, Any], or None if not a control msg."""
    t = msg.get("type")
    if t == "chat":
        from area.web.chat import classify_intent, is_factory_question
        from area.web.chat import route as chat_route

        message = str(msg.get("message", ""))
        app = str(msg.get("app") or "")
        intent = classify_intent(message)
        # Fast, free, governed paths: greetings, factory-state questions, and a
        # change command on a selected app. Everything else (a new-app idea, an
        # unclear ask, free-form talk) goes to the KEYLESS forcing-intake LLM, which
        # converges on a spec and then hands BACK to the oracle-loop via `run`.
        fast = (intent == "smalltalk"
                or (intent == "change" and app)
                or (intent == "question" and is_factory_question(message)))
        if fast:
            return {"type": "chat_reply", "id": msg.get("id"), **chat_route(message, app)}
        from area.web.intake import intake_turn

        res = intake_turn(msg.get("history") or [], message)
        out = {"type": "chat_reply", "id": msg.get("id"),
               "action": "spec_ready" if res["ready"] else "intake",
               "reply": res["reply"]}
        if res["ready"]:
            out["requirement"] = res["requirement"]
        return out
    if t == "apps":
        from area.web.jobs import list_apps

        return {"type": "apps", "apps": [a["name"] for a in list_apps()]}
    return None


def _area_cmd() -> list[str]:
    """How to invoke the `area` CLI from inside the runner process."""
    return [sys.executable, "-m", "area.cli"]


def _env() -> dict[str, Any]:
    e = dict[str, Any](os.environ)
    e.setdefault("npm_config_cache", str(Path.home() / ".cache" / "npm-area"))
    e["OPENHANDS_SUPPRESS_BANNER"] = "1"
    e["PYTHONUNBUFFERED"] = "1"
    return e


# Job kinds whose `area` command accepts --backend (acp keyless | llm keyed).
_BACKEND_KINDS = {"run", "clone", "intake", "iterate"}


def job_argv_for(kind: str, params: dict[str, Any] | None) -> list[str]:
    """`area` args for a job, honoring AREA_RUNNER_BACKEND (headless/container
    runners set it to 'llm' with LLM_API_KEY+LLM_MODEL; the default keyless 'acp'
    needs a Claude Code login on the runner)."""
    argv = job_argv(kind, params)
    be = (os.getenv("AREA_RUNNER_BACKEND") or "").strip()
    if be and kind in _BACKEND_KINDS and "--backend" not in argv:
        argv += ["--backend", be]
    return argv


def _store_chunk(uploads: dict[str, Any], msg: dict[str, Any], *, max_chunks: int = 1024) -> None:
    """Accumulate one base64 chunk of a requirement-doc upload, keyed by its uid.
    So an upload of ANY size crosses the relay as a sequence of small frames (each
    under the coordinator's per-frame cap) and is reassembled here."""
    uid = str(msg.get("uid") or "")
    if not uid:
        return
    try:
        i, n = int(msg.get("i") or 0), int(msg.get("n") or 0)
    except (TypeError, ValueError):
        return
    rec = uploads.setdefault(uid, {"name": str(msg.get("name") or "document"), "n": n, "parts": {}})
    rec["n"] = n
    if len(rec["parts"]) < max_chunks:
        rec["parts"][i] = str(msg.get("data") or "")


def _decode_doc(p: dict[str, Any], uploads: dict[str, Any] | None) -> tuple[str | None, bytes | None]:
    """Resolve an attached requirement doc to (name, bytes): either a chunked upload
    (doc_uid, reassembled from `uploads`) or a small inline base64 (doc_b64). Pops
    the doc keys from p. Returns (None, None) if absent/incomplete."""
    import base64

    if p.get("doc_uid") and uploads is not None:
        rec = uploads.pop(str(p.pop("doc_uid")), None)
        if not rec:
            return None, None
        n = rec.get("n") or len(rec["parts"])
        if len(rec["parts"]) < n:
            return None, None  # incomplete — missing chunks
        b64 = "".join(rec["parts"].get(i, "") for i in range(n))
        return (rec.get("name") or "document"), base64.b64decode(b64)
    if p.get("doc_b64"):
        name = str(p.pop("doc_name", "document"))
        return name, base64.b64decode(p.pop("doc_b64"))
    p.pop("doc_name", None)
    return None, None


def fold_requirement_doc(params: dict[str, Any] | None, uploads: dict[str, Any] | None = None) -> tuple[dict[str, Any], str | None]:
    """Fold an uploaded requirement doc (chunked upload or inline base64) into the
    run job's `requirement`, extracting text with the same parser the local
    dashboard uses. Returns (params, note_or_None); never raises."""
    p = dict[str, Any](params or {})
    try:
        doc_name, raw = _decode_doc(p, uploads)
    except Exception as e:  # noqa: BLE001
        return p, f"doc parse warn: {e}"
    if raw is None or doc_name is None:
        # _decode_doc only ever yields bytes together with a name; stating the
        # invariant here is better than casting it away.
        return p, None
    from area.web.upload import parse_file

    try:
        text = parse_file(doc_name, raw).strip()
    except Exception as e:  # noqa: BLE001 — never fail a job on doc parsing
        return p, f"doc parse warn: {e}"
    if text:
        base = (p.get("requirement") or "").strip()
        p["requirement"] = f"{base}\n\n=== {doc_name} ===\n{text}".strip()
        return p, f"đọc tài liệu {doc_name}: {len(text)} ký tự ({len(raw)//1024}KB)"
    return p, None


async def _exec_job(ws: Any, job: dict[str, Any], uploads: dict[str, Any] | None = None) -> None:
    jid = job["id"]
    params, note = fold_requirement_doc(job.get("params"), uploads)
    alive = True

    async def tell(obj: dict[str, Any]) -> None:
        """Stream a frame to the UI, but never let a dead socket kill the build: if
        the ws has dropped we stop sending and keep running."""
        nonlocal alive
        if not alive:
            return
        try:
            await ws.send(encode(obj))
        except Exception:  # noqa: BLE001 — ws dropped mid-job; build keeps going
            alive = False

    if note:
        await tell(log_msg(jid, f"[runner] {note}"))
    try:
        argv = job_argv_for(job["kind"], params)
    except ValueError as e:
        await tell(status_msg(jid, "failed", None))
        await tell(log_msg(jid, f"[runner] bad job: {e}"))
        return
    await tell(status_msg(jid, "running"))
    proc = await asyncio.create_subprocess_exec(
        *_area_cmd(), *argv, cwd=str(ROOT), env=_env(),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    assert proc.stdout is not None
    # ALWAYS drain stdout to the end so a dropped ws can't leave the subprocess
    # blocked on a full pipe — the build runs to completion on disk regardless.
    async for raw in proc.stdout:
        await tell(log_msg(jid, raw.decode(errors="ignore").rstrip("\n")))
    rc = await proc.wait()
    await tell(status_msg(jid, "done" if rc == 0 else "failed", rc))


async def _keepalive(ws: Any, interval: float = 25.0) -> None:
    """Send a tiny app-level ping periodically to keep an idle socket alive. The
    coordinator drops `ping` frames (never relays them). Exits quietly when the
    socket is gone (cancelled by the serve loop)."""
    try:
        while True:
            await asyncio.sleep(interval)
            await ws.send(encode({"type": "ping"}))
    except Exception:  # noqa: BLE001 — cancelled or socket closed
        pass


async def _serve_once(url: str, token: str | None) -> None:
    """One live connection: dial in, announce, then serve jobs/control until the
    socket closes (raises on any connection problem so the caller can reconnect)."""
    import websockets

    uploads: dict[str, Any] = {}  # in-flight requirement-doc uploads, reassembled by uid
    # Lenient ping_timeout + an app-level keepalive keep the socket warm so an idle
    # connection isn't torn down ("no close frame") between jobs.
    async with websockets.connect(url, max_size=None, ping_interval=15, ping_timeout=30) as ws:
        await ws.send(encode(hello_msg("runner", token)))
        print("[runner] connected — waiting for jobs (Ctrl-C to stop)", flush=True)
        ka = asyncio.create_task(_keepalive(ws))
        try:
            async for raw in ws:
                msg = decode(raw)
                if msg.get("type") == "upload":
                    _store_chunk(uploads, msg)
                    continue
                if is_valid_job(msg):
                    print(f"[runner] job {msg.get('id')} · {msg.get('kind')}", flush=True)
                    await _exec_job(ws, msg, uploads)
                    continue
                reply = handle_control(msg)
                if reply is not None:
                    await ws.send(encode(reply))
        finally:
            ka.cancel()


async def _run(coord_url: str, token: str | None, *,
               max_attempts: int | None = None,
               _sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
               ) -> None:
    """Keep a runner connected. Reconnects with capped exponential backoff after a
    dropped/closed socket (e.g. a coordinator redeploy) — the UI already auto-
    reconnects, so now the data plane does too. max_attempts bounds the loop (for
    tests); None = run until Ctrl-C."""
    from urllib.parse import quote

    base = coord_url.rstrip("/") + "/ws/runner"
    url = base + ("?token=" + quote(token) if token else "")
    delay, attempts = 1.0, 0
    while True:
        attempts += 1
        try:
            print(f"[runner] connecting to {base} …", flush=True)
            await _serve_once(url, token)
            print("[runner] disconnected.", flush=True)
            delay = 1.0  # we were connected → reset backoff
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — refused/dropped/closed: reconnect
            print(f"[runner] connection lost: {e}", flush=True)
        if max_attempts is not None and attempts >= max_attempts:
            return
        wait = min(delay, 15.0)
        print(f"[runner] reconnecting in {wait:.0f}s… (Ctrl-C to stop)", flush=True)
        await _sleep(wait)
        delay = min(delay * 2, 15.0)


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
