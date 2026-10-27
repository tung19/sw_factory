"""area.net.server — the coordinator (control plane). Relays jobs UI↔runner and
serves a minimal UI. Runs no agents, stores no secrets (ADR 0002). P0: one
in-memory channel.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from starlette.applications import Starlette
from starlette.responses import HTMLResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from area.net.hub import Hub
from area.net.protocol import encode

HUB = Hub()
STATIC = Path(__file__).resolve().parent / "static"


def _require_token() -> bool:
    """Public mode: reject tokenless connections (so there's no open shared
    channel). Enabled by AREA_COORD_REQUIRE_TOKEN=1 (or the legacy AREA_COORD_TOKEN
    being set). Off by default → local dev works tokenless on the LOCAL channel."""
    v = (os.getenv("AREA_COORD_REQUIRE_TOKEN") or "").strip().lower()
    if v in ("1", "true", "yes"):
        return True
    return bool((os.getenv("AREA_COORD_TOKEN") or "").strip())


def _channel(scope: Any) -> str:
    """The pairing token = the channel key. Empty → the LOCAL channel."""
    qs = parse_qs(scope.get("query_string", b"").decode())
    tok: str = (qs.get("token") or [""])[0]
    return tok


async def index(request: Any) -> HTMLResponse:
    # The page is a static shell with no secrets; the token gates the channel.
    return HTMLResponse((STATIC / "index.html").read_text())


async def ws_runner(ws: WebSocket) -> None:
    key = _channel(ws.scope)
    if _require_token() and not key:
        await ws.close(code=1008)
        return
    await ws.accept()

    async def send(text: str) -> None:
        await ws.send_text(text)

    HUB.connect_runner(key, send)
    await HUB.from_runner(key, encode({"type": "coord", "runner": True}))
    try:
        while True:
            raw = await ws.receive_text()
            await HUB.from_runner(key, raw)
    except WebSocketDisconnect:
        pass
    finally:
        HUB.disconnect_runner(key, send)
        await HUB.from_runner(key, encode({"type": "coord", "runner": False}))


async def ws_ui(ws: WebSocket) -> None:
    key = _channel(ws.scope)
    if _require_token() and not key:
        await ws.close(code=1008)
        return
    await ws.accept()

    async def send(text: str) -> None:
        await ws.send_text(text)

    HUB.connect_ui(key, send)
    await send(encode({"type": "coord", "runner": HUB.has_runner(key)}))
    try:
        while True:
            raw = await ws.receive_text()
            await HUB.from_ui(key, raw)
    except WebSocketDisconnect:
        pass
    finally:
        HUB.disconnect_ui(key, send)


app = Starlette(routes=[
    Route("/", index),
    WebSocketRoute("/ws/runner", ws_runner),
    WebSocketRoute("/ws/ui", ws_ui),
])
