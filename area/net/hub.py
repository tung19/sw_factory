"""area.net.hub — the coordinator's relay. It forwards raw frames between one
runner and any number of UIs, and drops anything from a UI that isn't a valid
typed job. It executes nothing and stores no secrets (ADR 0002). P0: a single
channel (one runner + its UIs); accounts/pairing come in P2.
"""
from __future__ import annotations

from typing import Awaitable, Callable

from area.net.protocol import decode, is_valid_job

Send = Callable[[str], Awaitable[None]]  # an async "send this text frame"


class Hub:
    def __init__(self) -> None:
        self._runner: Send | None = None
        self._uis: set[Send] = set()

    # --- connections ---------------------------------------------------------
    def connect_runner(self, send: Send) -> None:
        self._runner = send

    def disconnect_runner(self, send: Send | None = None) -> None:
        if send is None or send is self._runner:
            self._runner = None

    def connect_ui(self, send: Send) -> None:
        self._uis.add(send)

    def disconnect_ui(self, send: Send) -> None:
        self._uis.discard(send)

    def has_runner(self) -> bool:
        return self._runner is not None

    # --- routing -------------------------------------------------------------
    async def from_ui(self, raw: str) -> bool:
        """Forward a UI frame to the runner IFF it is a valid typed job.
        Returns True if forwarded. Invalid frames are dropped (not relayed)."""
        if not is_valid_job(decode(raw)) or self._runner is None:
            return False
        await self._runner(raw)
        return True

    async def from_runner(self, raw: str) -> None:
        """Broadcast a runner frame (log/status) to every connected UI."""
        for send in list(self._uis):
            try:
                await send(raw)
            except Exception:  # noqa: BLE001 — drop a dead UI, keep the rest
                self._uis.discard(send)
