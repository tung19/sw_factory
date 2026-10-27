"""area.web.auth — a token gate for the AREA dashboard (Jupyter-style).

The dashboard can trigger agent runs (filesystem + deploy power), so it must NOT
be open. Every request must present an access token one of three ways:
  * `?token=<t>` in the URL — a ONE-SHOT handoff: it sets the cookie and then
    REDIRECTS to the same path without the token, so the SPA's later
    fetch()/EventSource calls (which cannot set headers) stay authed while the token
    does not linger in the address bar, browser history, or a Referer header,
  * an `Authorization: Bearer <t>` header,
  * the `area_gui_token` cookie.

Token source: env `AREA_GUI_TOKEN` if set, else a random one generated once per
process (printed by `area gui`). Set `AREA_GUI_NO_AUTH=1` to deliberately disable
the gate (local, single-user only).

This is a PURE ASGI middleware (not Starlette's BaseHTTPMiddleware) so the SSE
log stream passes through untouched.
"""
from __future__ import annotations

import os
import secrets
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlencode

from starlette.types import ASGIApp, Message, Receive, Scope, Send

COOKIE_NAME = "area_gui_token"

_token: str | None = None
_auto = False


def get_token() -> str:
    """The dashboard access token: `AREA_GUI_TOKEN` if set, else a per-process
    random token (cached so every caller sees the same value)."""
    global _token, _auto
    if _token is None:
        env = (os.getenv("AREA_GUI_TOKEN") or "").strip()
        if env:
            _token, _auto = env, False
        else:
            _token, _auto = secrets.token_urlsafe(32), True
    return _token


def is_auto_token() -> bool:
    """True if the token was randomly generated (no AREA_GUI_TOKEN was set)."""
    get_token()
    return _auto


def auth_disabled() -> bool:
    return (os.getenv("AREA_GUI_NO_AUTH") or "").strip().lower() in ("1", "true", "yes")


def _reset_for_test() -> None:  # pragma: no cover - test helper
    global _token, _auto
    _token, _auto = None, False


def _presented_token(scope: Scope) -> str | None:
    """Pull a token from the Authorization header, ?token=, or the cookie."""
    headers: dict[str, str] = {
        k.decode().lower(): v.decode() for k, v in (scope.get("headers") or [])
    }
    auth = headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth[len("Bearer "):].strip()
    qs: dict[str, list[str]] = parse_qs(scope.get("query_string", b"").decode())
    if qs.get("token"):
        return qs["token"][0]
    raw_cookie = headers.get("cookie")
    if raw_cookie:
        jar = SimpleCookie()
        jar.load(raw_cookie)
        if COOKIE_NAME in jar:
            return jar[COOKIE_NAME].value
    return None


def _token_from_query(scope: Scope) -> bool:
    return bool(parse_qs(scope.get("query_string", b"").decode()).get("token"))


class TokenAuthMiddleware:
    """Reject HTTP requests without a valid token; pass everything else through."""

    def __init__(self, app: ASGIApp, token: str | None = None) -> None:
        self.app = app
        self._token = token

    @property
    def token(self) -> str:
        return self._token or get_token()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or auth_disabled():
            await self.app(scope, receive, send)
            return
        got = _presented_token(scope)
        if got and secrets.compare_digest(got, self.token):
            if not _token_from_query(scope):
                await self.app(scope, receive, send)
                return
            # A token in the URL is a handoff, not a channel. For a document request
            # we set the cookie and redirect to the clean path, so the token does not
            # persist in the address bar, the history entry, or a Referer header. An
            # API call cannot be redirected without breaking its client, so it only
            # gets the cookie.
            if (scope.get("method") in ("GET", "HEAD")
                    and not str(scope.get("path", "")).startswith("/api/")):
                await self._redirect_without_token(scope, send)
                return
            await self.app(scope, receive, self._cookie_send(send, scope))
            return
        await self._reject(scope, send)

    def _cookie_value(self, scope: Scope) -> bytes:
        """`Secure` only over TLS: setting it on plain http://localhost would make the
        browser drop the cookie outright and break the local flow."""
        attrs = f"{COOKIE_NAME}={self.token}; Path=/; HttpOnly; SameSite=Strict"
        if scope.get("scheme") == "https":
            attrs += "; Secure"
        return attrs.encode()

    async def _redirect_without_token(self, scope: Scope, send: Send) -> None:
        qs = parse_qs(scope.get("query_string", b"").decode())
        qs.pop("token", None)
        rest = urlencode(qs, doseq=True)
        target = str(scope.get("path") or "/") + (f"?{rest}" if rest else "")
        await send({
            "type": "http.response.start",
            "status": 303,
            "headers": [(b"location", target.encode()),
                        (b"set-cookie", self._cookie_value(scope)),
                        (b"content-length", b"0"),
                        # don't let an intermediary cache a redirect carrying Set-Cookie
                        (b"cache-control", b"no-store")],
        })
        await send({"type": "http.response.body", "body": b""})

    def _cookie_send(self, send: Send, scope: Scope) -> Send:
        """Wrap `send` to set the auth cookie once, on a query-token success."""
        cookie = self._cookie_value(scope)

        async def wrapped(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                headers.append((b"set-cookie", cookie))
                message = {**message, "headers": headers}
            await send(message)

        return wrapped

    async def _reject(self, scope: Scope, send: Send) -> None:
        if scope.get("path", "").startswith("/api/"):
            body, ctype = b'{"error":"unauthorized"}', b"application/json"
        else:
            body, ctype = _LOGIN_HTML, b"text/html; charset=utf-8"
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [(b"content-type", ctype),
                        (b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})


_LOGIN_HTML = (
    "<!doctype html><meta charset=utf-8><title>AREA — sign in</title>"
    "<body style='font-family:system-ui;max-width:32rem;margin:4rem auto;padding:0 1rem'>"
    "<h1>AREA dashboard</h1>"
    "<p>This dashboard controls agent runs and deploys, so it is protected.</p>"
    "<p>Open it with your access token (printed in the terminal running "
    "<code>area gui</code>, or set a fixed one via <code>AREA_GUI_TOKEN</code>):</p>"
    "<form onsubmit=\"location='/?token='+encodeURIComponent(this.t.value);return false\">"
    "<input name=t placeholder='paste access token' autofocus "
    "style='width:68%;padding:.45rem'>"
    "<button style='padding:.45rem .9rem'>Open</button></form>"
    "</body>"
).encode()
