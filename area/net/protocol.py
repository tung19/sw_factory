"""area.net.protocol — the typed wire protocol between a UI and a runner.

Only a FIXED set of job kinds crosses the wire — never arbitrary shell — so a
compromised coordinator can at most ask a runner to do an AREA command the user
could already run themselves (and deploy still has its human gate).
"""
from __future__ import annotations

import json

# Job kinds a UI may ask a runner to execute. Each maps to a real `area` command.
ALLOWED_KINDS = ("doctor", "run", "clone", "intake", "iterate", "deploy", "export")


def encode(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False)


def decode(raw: str) -> dict:
    try:
        out = json.loads(raw)
        return out if isinstance(out, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


# --- message constructors ----------------------------------------------------

def hello_msg(role: str, token: str | None = None) -> dict:
    return {"type": "hello", "role": role, "token": token}


def job_msg(jid: str, kind: str, params: dict | None = None) -> dict:
    return {"type": "job", "id": jid, "kind": kind, "params": params or {}}


def log_msg(jid: str, line: str) -> dict:
    return {"type": "log", "id": jid, "line": line}


def status_msg(jid: str, status: str, exit_code: int | None = None) -> dict:
    return {"type": "status", "id": jid, "status": status, "exit": exit_code}


def chat_msg(cid: str, message: str, app: str = "") -> dict:
    return {"type": "chat", "id": cid, "message": message, "app": app}


def apps_req() -> dict:
    return {"type": "apps"}


def is_valid_job(msg: dict) -> bool:
    return (
        isinstance(msg, dict)
        and msg.get("type") == "job"
        and msg.get("kind") in ALLOWED_KINDS
        and bool(msg.get("id"))
    )


def is_relayable_from_ui(msg: dict) -> bool:
    """What a UI is allowed to send to a runner: a typed job, a chat query, an
    apps-list request, or a requirement-document upload chunk. Anything else is
    dropped at the coordinator."""
    if is_valid_job(msg):
        return True
    return isinstance(msg, dict) and msg.get("type") in ("chat", "apps", "upload")


def job_argv(kind: str, params: dict | None = None) -> list[str]:
    """Translate a typed job into `area` CLI args. Raises on an unknown kind."""
    p = params or {}
    if kind == "doctor":
        return ["doctor"]
    if kind == "run":
        a = ["run", str(p.get("requirement", "")), "--name", str(p.get("name") or "app")]
        if p.get("target"):
            a += ["--target", str(p["target"])]
        if p.get("tdd"):
            a += ["--tdd"]
        return a
    if kind == "clone":
        return ["clone", str(p.get("source", "")), "--name", str(p.get("name") or "clone")]
    if kind == "intake":
        return ["intake", str(p.get("artifacts", "")), "--name", str(p.get("name") or "intake")]
    if kind == "iterate":
        return ["iterate", str(p.get("name", "")), str(p.get("instruction", ""))]
    if kind == "deploy":
        return ["deploy", str(p.get("name", "")), "--yes"]
    if kind == "export":
        a = ["export", str(p.get("name", ""))]
        if p.get("repo"):
            a += ["--repo", str(p["repo"])]
        if p.get("push"):
            a += ["--push"]
        return a
    raise ValueError(f"unknown job kind: {kind}")
