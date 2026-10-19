"""area.web.server — Starlette GUI for AREA (jobs, live logs, apps, deploy)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sse_starlette.sse import EventSourceResponse
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from area._util import safe_name
from area.web.auth import TokenAuthMiddleware
from area.web.chat import route as chat_route
from area.web.jobs import MANAGER, app_tree, list_apps, read_spec
from area.web.upload import save_intake

STATIC = Path(__file__).resolve().parent / "static"


async def index(request):
    return HTMLResponse((STATIC / "index.html").read_text())


async def api_jobs(request):
    if request.method == "POST":
        body = await request.json()
        kind = body.get("kind")
        params = body.get("params", {})
        if kind not in ("run", "clone", "intake", "deploy", "iterate"):
            return JSONResponse({"error": "bad kind"}, status_code=400)
        if not params.get("name"):
            return JSONResponse({"error": "name required"}, status_code=400)
        required = {"run": "requirement", "clone": "source",
                    "intake": "artifacts", "iterate": "instruction"}.get(kind)
        if required and not params.get(required):
            return JSONResponse({"error": f"{required} required"}, status_code=400)
        try:
            jid = MANAGER.start(kind, params)
        except (KeyError, ValueError) as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        return JSONResponse({"id": jid})
    return JSONResponse(MANAGER.list())


async def api_upload(request):
    """Parse an uploaded requirement doc (PDF/Word/MD) + optional description
    into intake artifacts. Returns {dir, files, text, chars}."""
    form = await request.form()
    name = (form.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "name required"}, status_code=400)
    description = form.get("description") or ""
    files = [
        (u.filename, await u.read())
        for u in form.getlist("file")
        if getattr(u, "filename", None)
    ]
    if not files and not description.strip():
        return JSONResponse({"error": "upload a file or type a description"},
                            status_code=400)
    try:
        return JSONResponse(save_intake(name, files, description))
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=400)


async def api_chat(request):
    """Governed, keyless chat box: classify the message and return an action
    (answer from state, or a proposed iterate/run the UI confirms). Never pipes
    raw instructions to the model — changes flow through the oracle pipeline."""
    body = await request.json()
    msg = (body.get("message") or "").strip()
    if not msg:
        return JSONResponse({"error": "empty message"}, status_code=400)
    app = safe_name(body.get("app") or "")
    try:
        return JSONResponse(chat_route(msg, app))
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"action": "answer", "reply": f"Lỗi: {e}"})


async def api_job(request):
    j = MANAGER.get(request.path_params["id"])
    return JSONResponse(j or {}, status_code=200 if j else 404)


async def api_stream(request):
    jid = request.path_params["id"]
    logp = MANAGER.log_path(jid)

    async def gen():
        pos = 0
        for _ in range(50):
            if logp.exists():
                break
            await asyncio.sleep(0.1)
        while True:
            if logp.exists():
                data = logp.read_bytes()
                if len(data) > pos:
                    chunk = data[pos:].decode(errors="ignore")
                    pos = len(data)
                    for line in chunk.splitlines():
                        yield {"data": line}
            if not MANAGER.is_running(jid):
                if logp.exists():
                    data = logp.read_bytes()
                    if len(data) > pos:
                        for line in data[pos:].decode(errors="ignore").splitlines():
                            yield {"data": line}
                yield {"event": "done", "data": json.dumps(MANAGER.get(jid) or {})}
                break
            await asyncio.sleep(0.5)

    return EventSourceResponse(gen())


async def api_job_log(request):
    """One-shot full log of a job (for snapshot rendering — no live stream)."""
    logp = MANAGER.log_path(request.path_params["id"])
    text = logp.read_text(errors="ignore") if logp.exists() else ""
    from starlette.responses import PlainTextResponse

    return PlainTextResponse(text)


async def api_apps(request):
    apps = list_apps()
    urls = {}
    for j in MANAGER.list():
        if j.get("url") and j.get("name"):
            urls.setdefault(j["name"], j["url"])
    for a in apps:
        a["url"] = urls.get(a["name"])
    return JSONResponse(apps)


async def api_spec(request):
    return JSONResponse(read_spec(request.path_params["name"]))


async def api_tree(request):
    return JSONResponse(app_tree(request.path_params["name"]))


app = Starlette(
    routes=[
        Route("/", index),
        Route("/api/upload", api_upload, methods=["POST"]),
        Route("/api/chat", api_chat, methods=["POST"]),
        Route("/api/jobs", api_jobs, methods=["GET", "POST"]),
        Route("/api/jobs/{id}", api_job),
        Route("/api/jobs/{id}/stream", api_stream),
        Route("/api/jobs/{id}/log", api_job_log),
        Route("/api/apps", api_apps),
        Route("/api/apps/{name}/spec", api_spec),
        Route("/api/apps/{name}/tree", api_tree),
    ],
    # PR6: the dashboard drives agent runs + deploys, so gate every request on a
    # token (Jupyter-style). Disable only with AREA_GUI_NO_AUTH=1.
    middleware=[Middleware(TokenAuthMiddleware)],
)
