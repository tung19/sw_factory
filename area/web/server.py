"""area.web.server — Starlette GUI for AREA (jobs, live logs, apps, deploy)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sse_starlette.sse import EventSourceResponse
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from area.web.jobs import MANAGER, app_tree, list_apps, read_spec

STATIC = Path(__file__).resolve().parent / "static"


async def index(request):
    return HTMLResponse((STATIC / "index.html").read_text())


async def api_jobs(request):
    if request.method == "POST":
        body = await request.json()
        kind = body.get("kind")
        params = body.get("params", {})
        if kind not in ("run", "clone", "deploy"):
            return JSONResponse({"error": "bad kind"}, status_code=400)
        if not params.get("name"):
            return JSONResponse({"error": "name required"}, status_code=400)
        jid = MANAGER.start(kind, params)
        return JSONResponse({"id": jid})
    return JSONResponse(MANAGER.list())


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


app = Starlette(routes=[
    Route("/", index),
    Route("/api/jobs", api_jobs, methods=["GET", "POST"]),
    Route("/api/jobs/{id}", api_job),
    Route("/api/jobs/{id}/stream", api_stream),
    Route("/api/apps", api_apps),
    Route("/api/apps/{name}/spec", api_spec),
    Route("/api/apps/{name}/tree", api_tree),
])
