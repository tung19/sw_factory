"""area.net.hub — the coordinator's relay, keyed by CHANNEL (ADR 0002, P2).

Each pairing **token** is its own private channel: a UI on token X only ever
reaches the runner that registered with token X, and vice-versa. So many users
share one coordinator, each isolated to their own runner. Empty token = the
"local" channel (single-user local dev). The relay still forwards only valid
typed messages and executes nothing / stores no secrets.
"""
from __future__ import annotations

from typing import Awaitable, Callable

from area.net.protocol import decode, is_relayable_from_ui

Send = Callable[[str], Awaitable[None]]
LOCAL = ""  # the default channel key when no token is given (local dev)


class _Channel:
    def __init__(self) -> None:
        self.runner: Send | None = None
        self.uis: set[Send] = set()

    def empty(self) -> bool:
        return self.runner is None and not self.uis


class Hub:
    def __init__(self) -> None:
        self._ch: dict[str, _Channel] = {}

    def _get(self, key: str) -> _Channel:
        return self._ch.setdefault(key, _Channel())

    def _gc(self, key: str) -> None:
        c = self._ch.get(key)
        if c and c.empty():
            self._ch.pop(key, None)

    # --- connections (per channel) -------------------------------------------
    def connect_runner(self, key: str, send: Send) -> None:
        self._get(key).runner = send

    def disconnect_runner(self, key: str, send: Send | None = None) -> None:
        c = self._ch.get(key)
        if c and (send is None or send is c.runner):
            c.runner = None
            self._gc(key)

    def connect_ui(self, key: str, send: Send) -> None:
        self._get(key).uis.add(send)

    def disconnect_ui(self, key: str, send: Send) -> None:
        c = self._ch.get(key)
        if c:
            c.uis.discard(send)
            self._gc(key)

    def has_runner(self, key: str) -> bool:
        c = self._ch.get(key)
        return bool(c and c.runner is not None)

    def channel_count(self) -> int:
        return len(self._ch)

    # --- routing (within one channel) ----------------------------------------
    async def from_ui(self, key: str, raw: str) -> bool:
        """Forward a UI frame to THIS channel's runner iff it's a relayable typed
        message (job / chat / apps). Cross-channel is impossible."""
        c = self._ch.get(key)
        if not c or c.runner is None or not is_relayable_from_ui(decode(raw)):
            return False
        await c.runner(raw)
        return True

    async def from_runner(self, key: str, raw: str) -> None:
        """Broadcast a runner frame to THIS channel's UIs only."""
        c = self._ch.get(key)
        if not c:
            return
        for send in list(c.uis):
            try:
                await send(raw)
            except Exception:  # noqa: BLE001
                c.uis.discard(send)
