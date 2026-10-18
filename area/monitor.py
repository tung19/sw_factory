"""area.monitor — production monitoring of DEPLOYED apps + self-healing watch.

- monitor/status: HTTP health/latency probing of the live Cloudflare URL.
- cf_logs: best-effort Worker logs via `wrangler tail`.
- watch: the closed loop — probe -> if unhealthy, capture the symptom, `heal`
  (fix at spec level) -> rebuild -> HUMAN GATE -> redeploy (rollback available).
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from area._util import safe_name

_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = _ROOT / "workspace"
DEPLOYS = WORKSPACE / ".area" / "deploys"
MONDIR = WORKSPACE / ".area" / "monitor"


def record_deploy(name: str, url: str) -> None:
    DEPLOYS.mkdir(parents=True, exist_ok=True)
    (DEPLOYS / f"{safe_name(name)}.url").write_text(url.strip())


def deployed_url(name: str) -> Optional[str]:
    name = safe_name(name)
    p = DEPLOYS / f"{name}.url"
    if p.exists() and p.read_text().strip():
        return p.read_text().strip()
    jobs = WORKSPACE / ".area" / "jobs.json"  # fallback: GUI deploy jobs
    if jobs.exists():
        try:
            rows = sorted(json.loads(jobs.read_text()),
                          key=lambda r: r.get("ts", 0), reverse=True)
            for j in rows:
                if j.get("name") == name and j.get("url"):
                    return j["url"]
        except Exception:
            pass
    return None


def _probe(url: str, timeout: float = 15.0) -> dict:
    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "area-monitor"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            code = r.getcode()
            r.read(2048)
        return {"ok": 200 <= code < 400, "code": code,
                "ms": round((time.time() - t0) * 1000), "err": None}
    except Exception as e:
        return {"ok": False, "code": None,
                "ms": round((time.time() - t0) * 1000), "err": str(e)[:200]}


def _resolve(name_or_url: str, health: str) -> tuple[str, str]:
    if name_or_url.startswith("http"):
        base, name = name_or_url.rstrip("/"), "adhoc"
    else:
        name = safe_name(name_or_url)
        base = deployed_url(name)
        if not base:
            raise RuntimeError(f"no deployed URL for {name} (deploy first, or pass a URL)")
        base = base.rstrip("/")
    url = base + (health if health.startswith("/") else "/" + health)
    return name, url


def monitor(name_or_url: str, *, checks: int = 5, interval: float = 5.0,
            health: str = "/") -> dict:
    name, url = _resolve(name_or_url, health)
    MONDIR.mkdir(parents=True, exist_ok=True)
    log = MONDIR / f"{name}.jsonl"
    results = []
    for i in range(checks):
        r = _probe(url)
        r["ts"], r["url"] = time.time(), url
        results.append(r)
        with log.open("a") as f:
            f.write(json.dumps(r) + "\n")
        print(f"  {'✅' if r['ok'] else '❌'} {url} -> {r['code'] or r['err']} ({r['ms']}ms)")
        if i < checks - 1:
            time.sleep(interval)
    ok = sum(1 for r in results if r["ok"])
    return {"name": name, "url": url, "checks": checks, "ok": ok,
            "uptime_pct": round(100 * ok / max(checks, 1), 1),
            "avg_ms": round(sum(r["ms"] for r in results) / max(len(results), 1)),
            "results": results}


def status(name: str, *, limit: int = 50) -> dict:
    name = safe_name(name)
    log = MONDIR / f"{name}.jsonl"
    recs = []
    if log.exists():
        for line in log.read_text().splitlines()[-limit:]:
            try:
                recs.append(json.loads(line))
            except Exception:
                pass
    ok = sum(1 for r in recs if r.get("ok"))
    lat = sorted(r["ms"] for r in recs if r.get("ms") is not None)
    return {"name": name, "url": deployed_url(name), "samples": len(recs),
            "uptime_pct": round(100 * ok / len(recs), 1) if recs else None,
            "avg_ms": round(sum(lat) / len(lat)) if lat else None,
            "p95_ms": (lat[int(len(lat) * 0.95) - 1] if lat else None),
            "recent_failures": [r for r in recs if not r.get("ok")][-5:]}


def cf_logs(name: str, *, seconds: int = 12) -> str:
    """Best-effort Worker logs via `wrangler tail` (needs wrangler login)."""
    app = WORKSPACE / "apps" / safe_name(name)
    if not app.exists():
        return ""
    env = dict(os.environ)
    env.setdefault("npm_config_cache", str(Path.home() / ".cache" / "npm-area"))
    try:
        proc = subprocess.run(
            ["bash", "-lc",
             f"timeout {seconds} npx -y wrangler tail --format pretty 2>&1 | head -80"],
            cwd=str(app), capture_output=True, text=True, env=env, timeout=seconds + 25)
        return (proc.stdout + proc.stderr).strip()[-4000:]
    except Exception as e:
        return f"(wrangler tail failed: {e})"


def watch(name: str, *, checks: int = 3, interval: float = 5.0, max_heals: int = 1,
          confirm: Optional[Callable[[str], bool]] = None,
          backend: str = "acp", model: Optional[str] = None) -> bool:
    """Closed-loop: probe -> heal -> rebuild -> human gate -> redeploy."""
    name = safe_name(name)
    if not deployed_url(name):
        raise RuntimeError(f"no deployed URL for {name} (deploy first)")
    heals = 0
    while True:
        print(f"[area] watch: probing {name} …")
        m = monitor(name, checks=checks, interval=interval)
        if m["ok"] == m["checks"]:
            print(f"[area] watch: healthy ({m['uptime_pct']}%, {m['avg_ms']}ms). done.")
            return True
        fails = [r for r in m["results"] if not r["ok"]]
        logs = cf_logs(name)
        symptom = ("Production health check is FAILING:\n"
                   + "\n".join(f"{r['url']} -> {r['code'] or r['err']} ({r['ms']}ms)"
                               for r in fails[:5])
                   + (f"\n\n--- recent worker logs ---\n{logs}" if logs else ""))
        if heals >= max_heals:
            print(f"[area] watch: unhealthy and max-heals reached. ALERT:\n{symptom}")
            return False
        heals += 1
        print(f"[area] watch: UNHEALTHY → heal #{heals} (fix at spec level)")
        from area.heal import heal as heal_fn

        res = heal_fn(name, symptom, backend=backend, model=model, rebuild=True)
        if not res.build_passed:
            print("[area] watch: heal/rebuild not green; ALERT, not deploying.")
            return False
        if not (confirm(name) if confirm else False):
            print("[area] watch: redeploy NOT confirmed (app rebuilt, not deployed).")
            return False
        from area.deploy import deploy as deploy_fn

        ok, _out, newurl = deploy_fn(WORKSPACE / "apps" / name)
        if ok:
            if newurl:
                record_deploy(name, newurl)
            print(f"[area] watch: ✅ redeployed {newurl or ''}")
        else:
            print("[area] watch: redeploy FAILED — consider `area rollback`.")
            return False
