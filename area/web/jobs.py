"""area.web.jobs — run AREA pipeline jobs as subprocesses, track + stream them.

Each job shells out to the `area` CLI (reuse + isolation). Logs go to a per-job
file (tailed by the GUI via SSE); metadata persists to workspace/.area/jobs.json
so history survives restarts.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path

from area._util import safe_name

ROOT = Path(__file__).resolve().parent.parent.parent
WORKSPACE = ROOT / "workspace"
STATE_DIR = WORKSPACE / ".area"
JOBS_JSON = STATE_DIR / "jobs.json"
LOG_DIR = STATE_DIR / "logs"
AREA_BIN = ROOT / ".venv" / "bin" / "area"

_URL_RE = re.compile(r"https://[A-Za-z0-9.\-]+\.(?:workers|pages)\.dev\S*")
_SKIP_DIRS = {
    "node_modules", ".next", ".vinext", ".open-next", ".cloudflare",
    ".openhands", ".wrangler", ".git",
}


def _env() -> dict:
    e = dict(os.environ)
    home = Path.home()
    e["PATH"] = f"{home / '.local' / 'bin'}:/usr/local/bin:/opt/homebrew/bin:" + e.get("PATH", "")
    e.setdefault("npm_config_cache", str(home / ".cache" / "npm-area"))
    e["OPENHANDS_SUPPRESS_BANNER"] = "1"
    e["PYTHONUNBUFFERED"] = "1"  # live log streaming
    return e


class JobManager:
    def __init__(self) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self._procs: dict[str, tuple] = {}
        self._jobs: dict[str, dict] = self._load()

    def _load(self) -> dict:
        if JOBS_JSON.exists():
            try:
                data = json.loads(JOBS_JSON.read_text())
                for j in data:
                    if j.get("status") == "running":
                        j["status"] = "interrupted"
                return {j["id"]: j for j in data}
            except Exception:
                return {}
        return {}

    def _save(self) -> None:
        try:
            JOBS_JSON.write_text(json.dumps(list(self._jobs.values()), indent=2))
        except Exception:
            pass

    def _cmd(self, kind: str, p: dict) -> list[str]:
        b = str(AREA_BIN)
        if kind == "run":
            c = [b, "run", p["requirement"], "--name", p["name"],
                 "--target", p.get("target", "cloudflare")]
            if p.get("deploy"):
                c += ["--deploy", "--yes"]
            return c
        if kind == "clone":
            c = [b, "clone", p["source"], "--name", p["name"],
                 "--kind", p.get("srcKind", "auto"),
                 "--target", p.get("target", "cloudflare")]
            if p.get("deploy"):
                c += ["--deploy", "--yes"]
            return c
        if kind == "deploy":
            return [b, "deploy", p["name"], "--yes"]
        raise ValueError(f"unknown job kind: {kind}")

    def start(self, kind: str, params: dict) -> str:
        params = {**params, "name": safe_name(params.get("name", ""))}
        jid = uuid.uuid4().hex[:12]
        cmd = self._cmd(kind, params)
        log = LOG_DIR / f"{jid}.log"
        f = open(log, "wb")
        proc = subprocess.Popen(
            cmd, cwd=str(ROOT), stdout=f, stderr=subprocess.STDOUT, env=_env()
        )
        self._procs[jid] = (proc, f)
        self._jobs[jid] = {
            "id": jid, "kind": kind, "params": params,
            "name": params.get("name"), "status": "running",
            "started": time.time(), "ended": None, "exit": None, "url": None,
            "cmd": " ".join(["area"] + cmd[1:]),
        }
        self._save()
        return jid

    def _finalize_if_done(self, jid: str) -> None:
        entry = self._jobs.get(jid)
        if not entry or entry["status"] != "running":
            return
        pf = self._procs.get(jid)
        if not pf:
            return
        proc, f = pf
        rc = proc.poll()
        if rc is None:
            return
        try:
            f.flush()
            f.close()
        except Exception:
            pass
        entry["exit"] = rc
        entry["ended"] = time.time()
        entry["status"] = "green" if rc == 0 else "failed"
        try:
            m = _URL_RE.search((LOG_DIR / f"{jid}.log").read_text(errors="ignore"))
            if m:
                entry["url"] = m.group(0)
        except Exception:
            pass
        self._procs.pop(jid, None)
        self._save()

    def list(self) -> list[dict]:
        for jid in list(self._procs):
            self._finalize_if_done(jid)
        return sorted(self._jobs.values(), key=lambda j: j["started"], reverse=True)

    def get(self, jid: str) -> dict | None:
        self._finalize_if_done(jid)
        return self._jobs.get(jid)

    def log_path(self, jid: str) -> Path:
        return LOG_DIR / f"{jid}.log"

    def is_running(self, jid: str) -> bool:
        self._finalize_if_done(jid)
        j = self._jobs.get(jid)
        return bool(j and j["status"] == "running")


def list_apps() -> list[dict]:
    apps = []
    appdir = WORKSPACE / "apps"
    if appdir.exists():
        for d in sorted(appdir.iterdir()):
            if not d.is_dir():
                continue
            apps.append({
                "name": d.name,
                "built": (d / "package.json").exists(),
                "hasSpec": (WORKSPACE / "specs" / d.name / "spec.yaml").exists(),
            })
    return apps


def read_spec(name: str) -> dict:
    sd = WORKSPACE / "specs" / safe_name(name)
    out = {"spec": "", "acceptance": ""}
    for key, fn in (("spec", "spec.yaml"), ("acceptance", "acceptance.yaml")):
        p = sd / fn
        if p.exists():
            out[key] = p.read_text(errors="ignore")
    return out


def app_tree(name: str, limit: int = 300) -> list[str]:
    ad = WORKSPACE / "apps" / safe_name(name)
    files = []
    if ad.exists():
        for p in sorted(ad.rglob("*")):
            if p.is_dir():
                continue
            rel = p.relative_to(ad)
            if any(part in _SKIP_DIRS for part in rel.parts):
                continue
            files.append(str(rel))
            if len(files) >= limit:
                break
    return files


MANAGER = JobManager()
