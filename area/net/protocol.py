"""area.net.protocol — the typed wire protocol between a UI and a runner.

Only a FIXED set of job kinds crosses the wire — never arbitrary shell — so a
compromised coordinator can at most ask a runner to do an AREA command the user
could already run themselves (and deploy still has its human gate).
"""
from __future__ import annotations

import json
from typing import Any

# Job kinds a UI may ask a runner to execute. Each maps to a real `area` command.
ALLOWED_KINDS = ("doctor", "run", "clone", "intake", "iterate", "deploy", "export")


def encode(obj: dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False)


def decode(raw: str | bytes) -> dict[str, Any]:
    """Accepts bytes as well as str: a websocket iterator yields either, and
    `json.loads` handles both — the old `str`-only signature was narrower than the
    function."""
    try:
        out = json.loads(raw)
        return out if isinstance(out, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


# --- message constructors ----------------------------------------------------

def hello_msg(role: str, token: str | None = None) -> dict[str, Any]:
    return {"type": "hello", "role": role, "token": token}


def job_msg(jid: str, kind: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"type": "job", "id": jid, "kind": kind, "params": params or {}}


def log_msg(jid: str, line: str) -> dict[str, Any]:
    return {"type": "log", "id": jid, "line": line}


def status_msg(jid: str, status: str, exit_code: int | None = None) -> dict[str, Any]:
    return {"type": "status", "id": jid, "status": status, "exit": exit_code}


def chat_msg(cid: str, message: str, app: str = "") -> dict[str, Any]:
    return {"type": "chat", "id": cid, "message": message, "app": app}


def apps_req() -> dict[str, Any]:
    return {"type": "apps"}


def is_valid_job(msg: dict[str, Any]) -> bool:
    return (
        isinstance(msg, dict)
        and msg.get("type") == "job"
        and msg.get("kind") in ALLOWED_KINDS
        and bool(msg.get("id"))
    )


def is_relayable_from_ui(msg: dict[str, Any]) -> bool:
    """What a UI is allowed to send to a runner: a typed job, a chat query, an
    apps-list request, or a requirement-document upload chunk. Anything else is
    dropped at the coordinator."""
    if is_valid_job(msg):
        return True
    return isinstance(msg, dict) and msg.get("type") in ("chat", "apps", "upload")


def _deploy_approval(p: dict[str, Any]) -> list[str]:
    """Turn the request's EXPLICIT approval into the deploy gate's --yes.

    A relayed job runs non-interactively on the runner, so it can never show the
    interactive PRODUCTION gate — which is why this used to hardcode `--yes`, and
    thereby bypassed the one human approval before production for a job arriving
    over the network. The approval now has to travel in the request
    (`confirm: true`), the same rule the local dashboard enforces in
    `area/web/jobs.py`. Missing it refuses the job instead of approving it:
    `runner._exec_job` turns the ValueError into a failed job the UI can see.
    """
    if not p.get("confirm"):
        raise ValueError(
            "deploy requires explicit approval: send confirm=true. A relayed job "
            "cannot display the interactive PRODUCTION gate, so the approval must "
            "be in the request.")
    return ["--yes"]


def job_argv(kind: str, params: dict[str, Any] | None = None) -> list[str]:
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
        if p.get("deploy"):
            # build → gates → deploy to the runner's OWN infra, human-approved
            a += ["--deploy", *_deploy_approval(p)]
        return a
    if kind == "clone":
        return ["clone", str(p.get("source", "")), "--name", str(p.get("name") or "clone")]
    if kind == "intake":
        return ["intake", str(p.get("artifacts", "")), "--name", str(p.get("name") or "intake")]
    if kind == "iterate":
        return ["iterate", str(p.get("name", "")), str(p.get("instruction", ""))]
    if kind == "deploy":
        return ["deploy", str(p.get("name", "")), *_deploy_approval(p)]
    if kind == "export":
        a = ["export", str(p.get("name", ""))]
        if p.get("repo"):
            a += ["--repo", str(p["repo"])]
        if p.get("push"):
            a += ["--push"]
        return a
    raise ValueError(f"unknown job kind: {kind}")
