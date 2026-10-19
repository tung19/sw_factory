"""area.net.server — the coordinator (control plane). Relays jobs UI↔runner and
serves a minimal UI. Runs no agents, stores no secrets (ADR 0002). P0: one
in-memory channel.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path
from urllib.parse import parse_qs

from starlette.applications import Starlette
from starlette.responses import HTMLResponse, PlainTextResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from area.net.hub import Hub
from area.net.protocol import encode

HUB = Hub()
STATIC = Path(__file__).resolve().parent / "static"


def _coord_token() -> str | None:
    t = (os.getenv("AREA_COORD_TOKEN") or "").strip()
    return t or None


def _authed(scope) -> bool:
    """When AREA_COORD_TOKEN is set (public exposure), require ?token= on both the
    page and the websockets. No token set → open (local use)."""
    t = _coord_token()
    if not t:
        return True
    qs = parse_qs(scope.get("query_string", b"").decode())
    got = (qs.get("token") or [None])[0]
    return bool(got) and secrets.compare_digest(got, t)


async def index(request):
    if not _authed(request.scope):
        return PlainTextResponse("unauthorized — thêm ?token=… vào URL", status_code=401)
    return HTMLResponse((STATIC / "index.html").read_text())


async def ws_runner(ws: WebSocket):
    if not _authed(ws.scope):
        await ws.close(code=1008)
        return
    await ws.accept()

    async def send(text: str) -> None:
        await ws.send_text(text)

    HUB.connect_runner(send)
    # let the UIs know a runner just attached
    await HUB.from_runner(encode({"type": "coord", "runner": True}))
    try:
        while True:
            raw = await ws.receive_text()
            await HUB.from_runner(raw)
    except WebSocketDisconnect:
        pass
    finally:
        HUB.disconnect_runner(send)
        await HUB.from_runner(encode({"type": "coord", "runner": False}))


async def ws_ui(ws: WebSocket):
    if not _authed(ws.scope):
        await ws.close(code=1008)
        return
    await ws.accept()

    async def send(text: str) -> None:
        await ws.send_text(text)

    HUB.connect_ui(send)
    await send(encode({"type": "coord", "runner": HUB.has_runner()}))
    try:
        while True:
            raw = await ws.receive_text()
            await HUB.from_ui(raw)
    except WebSocketDisconnect:
        pass
    finally:
        HUB.disconnect_ui(send)


app = Starlette(routes=[
    Route("/", index),
    WebSocketRoute("/ws/runner", ws_runner),
    WebSocketRoute("/ws/ui", ws_ui),
])
