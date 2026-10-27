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


# ---------- #13: a URL token is a handoff, not a channel ----------
def _recv():
    async def r():
        return {"type": "http.request", "body": b"", "more_body": False}
    return r


def _run(mw, scope):
    """Drive the ASGI middleware and collect what it sent."""
    import asyncio

    sent = []

    async def send(m):
        sent.append(m)

    asyncio.run(mw(scope, _recv(), send))
    return sent


def _scope(path="/", query=b"", method="GET", scheme="http"):
    return {"type": "http", "path": path, "query_string": query, "method": method,
            "scheme": scheme, "headers": []}


def test_url_token_redirects_to_strip_it(monkeypatch):
    """Regression (audit #13): the token used to stay in the URL after authenticating,
    so it persisted in the address bar, the history entry and any Referer — and in
    proxy/access logs. It is now a one-shot handoff: set the cookie, then 303 to the
    clean path."""
    A._reset_for_test()
    monkeypatch.setenv("AREA_GUI_TOKEN", "sekret")

    async def app(scope, receive, send):  # must NOT be reached
        raise AssertionError("the document request should have been redirected")

    sent = _run(A.TokenAuthMiddleware(app), _scope(query=b"token=sekret"))
    start = sent[0]
    assert start["status"] == 303
    hdrs = dict(start["headers"])
    assert hdrs[b"location"] == b"/"                     # token gone from the URL
    assert b"area_gui_token=sekret" in hdrs[b"set-cookie"]
    assert b"HttpOnly" in hdrs[b"set-cookie"] and b"SameSite=Strict" in hdrs[b"set-cookie"]
    assert hdrs[b"cache-control"] == b"no-store"


def test_redirect_keeps_other_query_params(monkeypatch):
    A._reset_for_test()
    monkeypatch.setenv("AREA_GUI_TOKEN", "sekret")
    sent = _run(A.TokenAuthMiddleware(lambda *a: None),
                _scope(path="/", query=b"token=sekret&tab=iterate"))
    assert dict(sent[0]["headers"])[b"location"] == b"/?tab=iterate"


def test_secure_flag_only_over_tls(monkeypatch):
    """`Secure` on plain http://localhost would make the browser drop the cookie and
    break the local flow, so it is set exactly when the scheme is https."""
    A._reset_for_test()
    monkeypatch.setenv("AREA_GUI_TOKEN", "sekret")
    mw = A.TokenAuthMiddleware(lambda *a: None)

    plain = dict(_run(mw, _scope(query=b"token=sekret"))[0]["headers"])
    assert b"Secure" not in plain[b"set-cookie"]

    tls = dict(_run(mw, _scope(query=b"token=sekret", scheme="https"))[0]["headers"])
    assert b"; Secure" in tls[b"set-cookie"]


def test_an_api_call_with_a_url_token_is_not_redirected(monkeypatch):
    """Redirecting an API call would break its client; it just gets the cookie."""
    A._reset_for_test()
    monkeypatch.setenv("AREA_GUI_TOKEN", "sekret")
    reached = []

    async def app(scope, receive, send):
        reached.append(scope["path"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    sent = _run(A.TokenAuthMiddleware(app),
                _scope(path="/api/jobs", query=b"token=sekret"))
    assert reached == ["/api/jobs"]
    assert sent[0]["status"] == 200
    assert b"area_gui_token=sekret" in dict(sent[0]["headers"])[b"set-cookie"]


def test_a_cookie_request_passes_through_without_a_redirect(monkeypatch):
    """The steady state after the handoff: no token in the URL, no redirect loop."""
    A._reset_for_test()
    monkeypatch.setenv("AREA_GUI_TOKEN", "sekret")
    reached = []

    async def app(scope, receive, send):
        reached.append(1)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    sc = _scope()
    sc["headers"] = [(b"cookie", b"area_gui_token=sekret")]
    sent = _run(A.TokenAuthMiddleware(app), sc)
    assert reached == [1] and sent[0]["status"] == 200
    assert not any(k == b"set-cookie" for k, _ in sent[0]["headers"])
