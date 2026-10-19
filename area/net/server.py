"""area.net.server — the coordinator (control plane). Relays jobs UI↔runner and
serves a minimal UI. Runs no agents, stores no secrets (ADR 0002). P0: one
in-memory channel.
"""
from __future__ import annotations

from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import HTMLResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from area.net.hub import Hub
from area.net.protocol import encode

HUB = Hub()
STATIC = Path(__file__).resolve().parent / "static"


async def index(request):
    return HTMLResponse((STATIC / "index.html").read_text())


async def ws_runner(ws: WebSocket):
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
