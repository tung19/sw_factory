"""PR6: the dashboard token gate (area/web/auth.py). Pure-ASGI driving — no HTTP
client dependency. Covers: reject without a token, accept via ?token= (and set a
cookie), Bearer header, cookie; reject a wrong token; JSON-vs-HTML 401 bodies;
the AREA_GUI_NO_AUTH escape hatch; and token resolution from the environment."""
import asyncio

import area.web.auth as A
from area.web.auth import TokenAuthMiddleware

TOKEN = "secret-abc-123"


async def _ok_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200,
                "headers": [(b"content-type", b"text/plain")]})
    await send({"type": "http.response.body", "body": b"ok"})


def _drive(path="/", query=b"", headers=None, token=TOKEN):
    mw = TokenAuthMiddleware(_ok_app, token=token)
    scope = {"type": "http", "path": path, "query_string": query,
             "headers": headers or []}
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(m):
        sent.append(m)

    asyncio.run(mw(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    hdrs = {k.decode().lower(): v.decode() for k, v in start["headers"]}
    set_cookie = [v.decode() for k, v in start["headers"] if k == b"set-cookie"]
    return {"status": start["status"], "body": body, "headers": hdrs, "set_cookie": set_cookie}


# ---- rejection ---------------------------------------------------------------

def test_no_token_rejects_page_as_html():
    r = _drive("/")
    assert r["status"] == 401 and r["headers"]["content-type"].startswith("text/html")
    assert b"access token" in r["body"]


def test_no_token_rejects_api_as_json():
    r = _drive("/api/apps")
    assert r["status"] == 401 and r["headers"]["content-type"] == "application/json"
    assert b"unauthorized" in r["body"]


def test_wrong_token_rejected():
    assert _drive("/", query=b"token=nope")["status"] == 401
    assert _drive("/api/apps", headers=[(b"authorization", b"Bearer nope")])["status"] == 401


# ---- acceptance --------------------------------------------------------------

def test_query_token_accepts_and_sets_cookie():
    r = _drive("/", query=f"token={TOKEN}".encode())
    assert r["status"] == 200 and r["body"] == b"ok"
    assert any(f"area_gui_token={TOKEN}" in c for c in r["set_cookie"])
    assert any("HttpOnly" in c and "SameSite=Strict" in c for c in r["set_cookie"])


def test_bearer_header_accepts_without_cookie():
    r = _drive("/api/apps", headers=[(b"authorization", f"Bearer {TOKEN}".encode())])
    assert r["status"] == 200 and r["set_cookie"] == []  # no query -> no cookie set


def test_cookie_accepts():
    r = _drive("/api/apps", headers=[(b"cookie", f"area_gui_token={TOKEN}".encode())])
    assert r["status"] == 200


# ---- escape hatch + env resolution ------------------------------------------

def test_no_auth_env_disables_gate(monkeypatch):
    monkeypatch.setenv("AREA_GUI_NO_AUTH", "1")
    assert _drive("/")["status"] == 200  # open despite no token


def test_token_from_env(monkeypatch):
    monkeypatch.setenv("AREA_GUI_TOKEN", "env-fixed-tok")
    A._reset_for_test()
    try:
        assert A.get_token() == "env-fixed-tok" and A.is_auto_token() is False
    finally:
        A._reset_for_test()


def test_token_auto_generated_when_unset(monkeypatch):
    monkeypatch.delenv("AREA_GUI_TOKEN", raising=False)
    A._reset_for_test()
    try:
        t = A.get_token()
        assert isinstance(t, str) and len(t) >= 20 and A.is_auto_token() is True
    finally:
        A._reset_for_test()
