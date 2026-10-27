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
from typing import IO, Any

from area._util import kill_process_group, safe_name

from area.paths import REPO as ROOT, WORKSPACE as WORKSPACE  # noqa: E402 (AREA_WORKSPACE-aware; `as` = explicit re-export for `from area.web.jobs import WORKSPACE`)

STATE_DIR = WORKSPACE / ".area"
JOBS_JSON = STATE_DIR / "jobs.json"
LOG_DIR = STATE_DIR / "logs"
AREA_BIN = ROOT / ".venv" / "bin" / "area"

_URL_RE = re.compile(r"https://[A-Za-z0-9.\-]+\.(?:workers|pages)\.dev\S*")
_SKIP_DIRS = {
    "node_modules", ".next", ".vinext", ".open-next", ".cloudflare",
    ".openhands", ".wrangler", ".git",
}


def _env() -> dict[str, str]:
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
        self._procs: dict[str, tuple[subprocess.Popen[bytes], IO[bytes]]] = {}
        self._jobs: dict[str, dict[str, Any]] = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
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
        # atomic write (temp + os.replace) so concurrent jobs can't tear jobs.json
        try:
            tmp = JOBS_JSON.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(list(self._jobs.values()), indent=2))
            os.replace(tmp, JOBS_JSON)
        except Exception:
            pass

    @staticmethod
    def _deploy_approval(p: dict[str, Any]) -> list[str]:
        """Turn the request's EXPLICIT approval into the deploy gate's --yes.

        A dashboard job runs non-interactively, so it can never show the production
        gate — which is why this used to hardcode `--yes` and thereby bypass the one
        human approval before production. The approval now has to travel in the
        request (`confirm: true`), so it is a recorded operator decision rather than
        a silent default. Missing it refuses the job instead of approving it."""
        if not p.get("confirm"):
            raise ValueError(
                "deploy requires explicit approval: send confirm=true. A dashboard "
                "job cannot display the interactive PRODUCTION gate, so the approval "
                "must be in the request.")
        return ["--yes"]

    @staticmethod
    def _flags(p: dict[str, Any]) -> list[str]:
        """TDD + gate + deploy flags shared by run/clone/intake."""
        f: list[str] = []
        if p.get("tdd"):
            f.append("--tdd")
        # clarify + spec-review are DEFAULT-ON in the CLI now; emit the explicit
        # flag when on (harmless no-op) and --no-* only on an explicit opt-out.
        if p.get("clarify"):
            f.append("--clarify")
        elif "clarify" in p:
            f.append("--no-clarify")
        if p.get("spec_review"):
            f.append("--spec-review")
        elif "spec_review" in p:
            f.append("--no-spec-review")
        if p.get("expected"):
            f += ["--expect", str(p["expected"])]
        if p.get("design"):
            f.append("--design")
        if p.get("all"):
            f.append("--all")
        else:
            for g in ("verify", "audit", "e2e", "chaos"):
                if p.get(g):
                    f.append("--" + g)
        if p.get("deploy"):
            f += ["--deploy", *JobManager._deploy_approval(p)]
        return f

    def _cmd(self, kind: str, p: dict[str, Any]) -> list[str]:
        b = str(AREA_BIN)
        target = p.get("target", "cloudflare")
        if kind == "run":
            return [b, "run", p["requirement"], "--name", p["name"],
                    "--target", target] + self._flags(p)
        if kind == "clone":
            return [b, "clone", p["source"], "--name", p["name"],
                    "--kind", p.get("srcKind", "auto"),
                    "--target", target] + self._flags(p)
        if kind == "intake":
            return [b, "intake", p["artifacts"], "--name", p["name"],
                    "--target", target] + self._flags(p)
        if kind == "inception":
            # AI-DLC front-end: produce artifacts with --yes (auto-accept each
            # bolt); the dashboard provides the human gate AFTER, via review/edit
            # of the artifacts before the build is kicked off.
            return [b, "inception", p["requirement"], "--name", p["name"],
                    "--yes", "--target", target]
        if kind == "iterate":
            # The "command box": fold a NL change request into the spec + rebuild.
            # TDD is on by default in the CLI; only pass --no-tdd on explicit opt-out.
            # Drop --tdd from shared flags (iterate's parser uses --no-tdd instead).
            cmd = [b, "iterate", p["name"], p["instruction"]]
            if p.get("target"):
                cmd += ["--target", p["target"]]
            if p.get("tdd") is False:
                cmd.append("--no-tdd")
            return cmd + [f for f in self._flags(p) if f != "--tdd"]
        if kind == "deploy":
            return [b, "deploy", p["name"], *self._deploy_approval(p)]
        raise ValueError(f"unknown job kind: {kind}")

    def start(self, kind: str, params: dict[str, Any]) -> str:
        params = {**params, "name": safe_name(params.get("name", ""))}
        jid = uuid.uuid4().hex[:12]
        cmd = self._cmd(kind, params)
        log = LOG_DIR / f"{jid}.log"
        f = open(log, "wb")
        proc = subprocess.Popen(
            cmd, cwd=str(ROOT), stdout=f, stderr=subprocess.STDOUT, env=_env(),
            # Own process group, so cancel() can stop the whole tree. Without it a
            # cancelled job's children (node/npm/playwright) keep running — and
            # killpg would target the dashboard's own group.
            start_new_session=True,
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

    def cancel(self, jid: str) -> bool:
        """Stop a running job and everything it spawned. False if there is nothing to
        stop (unknown id, or already finished).

        This is the kill switch the factory had no way to pull: a build that thrashes
        costs real money, and the cost gate only measures AFTER the fact."""
        entry = self._jobs.get(jid)
        pf = self._procs.get(jid)
        if not entry or entry.get("status") != "running" or not pf:
            return False
        proc, f = pf
        kill_process_group(proc)
        try:
            f.flush()
            f.close()
        except Exception:  # noqa: BLE001
            pass
        self._procs.pop(jid, None)
        entry["status"] = "cancelled"
        entry["ended"] = time.time()
        entry["exit"] = proc.poll()
        self._save()
        return True

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

    def list(self) -> list[dict[str, Any]]:
        for jid in list(self._procs):
            self._finalize_if_done(jid)
        return sorted(self._jobs.values(), key=lambda j: j["started"], reverse=True)

    def get(self, jid: str) -> dict[str, Any] | None:
        self._finalize_if_done(jid)
        return self._jobs.get(jid)

    def log_path(self, jid: str) -> Path:
        return LOG_DIR / f"{jid}.log"

    def is_running(self, jid: str) -> bool:
        self._finalize_if_done(jid)
        j = self._jobs.get(jid)
        return bool(j and j["status"] == "running")


def list_apps() -> list[dict[str, Any]]:
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


def read_spec(name: str) -> dict[str, str]:
    sd = WORKSPACE / "specs" / safe_name(name)
    out = {"spec": "", "acceptance": ""}
    for key, fn in (("spec", "spec.yaml"), ("acceptance", "acceptance.yaml")):
        p = sd / fn
        if p.exists():
            out[key] = p.read_text(errors="ignore")
    return out


def inception_dir(name: str) -> Path:
    return WORKSPACE / "specs" / safe_name(name) / "inception"


def read_inception(name: str) -> dict[str, Any]:
    """The four Inception artifact files (for the dashboard review/edit panel)."""
    d = inception_dir(name)
    files = {}
    if d.is_dir():
        for f in sorted(d.glob("*.md")):
            files[f.name] = f.read_text(errors="ignore")
    return {"dir": str(d), "files": files}


def save_inception(name: str, files: dict[str, str]) -> dict[str, Any]:
    """Persist the human-edited Inception artifacts back, emit a human-approved
    evidence record (correlated to the run's trace when present), and re-check the
    contract. Only *.md basenames are written (no path traversal)."""
    from area.inception import validate_artifacts
    from area.intake.aidlc import emit_evidence, new_trace_id

    d = inception_dir(name)
    d.mkdir(parents=True, exist_ok=True)
    written = []
    for fn, content in (files or {}).items():
        base = Path(str(fn)).name
        if base.endswith(".md") and isinstance(content, str):
            (d / base).write_text(content)
            written.append(base)
    # reuse the run's trace_id if the trail has one, so the human-approved event
    # correlates with the inception run that produced the artifacts
    trace = new_trace_id()
    trail = d / "aidlc_trace.jsonl"
    if trail.exists():
        try:
            import json as _json

            lines = [l for l in trail.read_text().splitlines() if l.strip()]
            if lines:
                trace = _json.loads(lines[-1]).get("trace", trace)
        except Exception:  # noqa: BLE001
            pass
    emit_evidence(d, trace, "inception.human_approved", {"files": written})
    return {"ok": True, "dir": str(d), "written": written,
            "warnings": validate_artifacts(d)}


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
