"""area.verify.perf — live perf / load budget gate (PR4, §11).

NFR (area.verify.nfr) measures the artifact *statically* (sizes, dep count) and
blocks on budget. This gate is its runtime sibling: it BOOTS the built app on a
local port, fires concurrent HTTP load at it, and measures latency percentiles,
throughput and error rate — catching gross runtime regressions (an O(n²) render,
a blocking handler, a route that 500s under load) that a static measure cannot.

Same oracle posture as nfr / audit tier-2:
  - workspace/specs/<name>/perf.yaml present  → BLOCKING. Your values override the
    lenient defaults, and the FULL resulting budget blocks — so to loosen one
    metric, set it explicitly (every unlisted default still applies and blocks).
  - no perf.yaml                              → lenient defaults, ADVISORY (or --strict)

perf.yaml is a flat `metric: number` map, e.g.:
    p95_ms: 800
    error_rate_pct: 0.5
    throughput_rps: 20

HONEST SCOPE: this is a *relative responsiveness smoke* against a locally-booted
server (preferring a production `start`/`preview` script, falling back to `dev`),
not an absolute production SLO — dev-server latency is not edge latency. The
defaults are lenient accordingly; commit a perf.yaml for real, blocking budgets.
It is dependency-free (stdlib threads + urllib) and, like nfr, SKIPS (never fails
the build) when it cannot boot or reach the app — a gate that cannot measure must
not block. Metrics are directional: latency/error are ceilings (ok = value ≤
limit); throughput is a floor (ok = value ≥ limit).
"""
from __future__ import annotations

import json
import re
import socket
import subprocess
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Thread
from typing import Any, Optional

from area._util import kill_process_group, safe_name
from area.engine import scrubbed_env
from area.paths import WORKSPACE  # noqa: E402 (leaf single-source; avoids importing the whole pipeline+SDK behind a gate)
from area.verify.nfr import parse_budget_yaml  # shared flat-budget parser

# Metrics whose budget is a FLOOR (bigger is better); everything else is a ceiling.
_FLOOR = ("throughput_rps",)

# Guessed, lenient defaults (advisory unless the user commits real budgets). Sized
# for a locally-booted dev/preview server of a small app, after warm-up.
DEFAULT_BUDGET: dict[str, float] = {
    "p50_ms": 500,          # median response
    "p95_ms": 1500,         # tail
    "p99_ms": 3000,         # worst-case tail
    "error_rate_pct": 1,    # share of non-2xx/3xx or failed requests
    "throughput_rps": 5,    # FLOOR: sustained requests/sec
}

# Server-ready banner emitted by Next/Vite/most Node servers on boot.
_URL_RE = re.compile(r"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]):(\d+)")


def _env() -> dict[str, str]:
    # Built on `scrubbed_env()`, not `os.environ`: every command this module launches
    # runs the GENERATED app — agent-authored package.json scripts, so arbitrary
    # `postinstall`/build code — and must not inherit the deploy/cloud tokens this
    # process holds. Only those named keys are dropped; npm/node configuration and PATH
    # are preserved, which is what keeps the build working.
    e = scrubbed_env()
    e.setdefault("npm_config_cache", str(Path.home() / ".cache" / "npm-area"))
    return e


def _free_port() -> int:
    """Grab a currently-free TCP port. There is an inherent TOCTOU gap between
    release and the app's bind, but it is far safer than the framework default
    (next start defaults to :3000 and crashes on a collision instead of bumping)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])
    finally:
        s.close()


# ---- pure: percentiles, evaluation, budget sourcing -----------------------------

def percentile(sorted_ms: list[float], pct: float) -> float:
    """Nearest-rank percentile of an ascending list (pct in 0..100)."""
    if not sorted_ms:
        return 0.0
    k = max(1, min(len(sorted_ms), (int((pct / 100.0) * len(sorted_ms) + 0.999999))))
    return sorted_ms[k - 1]


def evaluate(metrics: dict[str, float], budget: dict[str, float]) -> list[dict[str, Any]]:
    """Per-metric verdicts. Only metrics present in BOTH are gated. Direction-aware:
    a FLOOR metric passes when value >= limit; a ceiling when value <= limit."""
    out: list[dict[str, Any]] = []
    for k, limit in budget.items():
        if k not in metrics:
            continue
        v = metrics[k]
        ok = v >= limit if k in _FLOOR else v <= limit
        out.append({"metric": k, "value": v, "limit": limit, "ok": ok,
                    "floor": k in _FLOOR})
    return out


def load_budget(name: str, *, strict: bool = False,
                root: Optional[Path] = None) -> tuple[dict[str, float], bool]:
    """Return (budget, blocking). A spec-level perf.yaml means the user committed
    real budgets → blocking; its values override the defaults and the FULL merged
    budget blocks (set a metric explicitly to loosen it). Otherwise defaults,
    advisory unless --strict. (Mirrors area.verify.nfr.load_budget.)"""
    root = Path(root) if root else WORKSPACE
    perf = root / "specs" / name / "perf.yaml"
    budget: dict[str, float] = dict(DEFAULT_BUDGET)
    blocking = strict
    if perf.exists():
        blocking = True
        budget.update(parse_budget_yaml(perf.read_text()))
    return budget, blocking


# ---- booting the app + firing load ----------------------------------------------

def _pick_start_cmd(app: Path) -> tuple[Optional[str], Optional[str]]:
    """Choose a server script. Prefer a production server when a build exists
    (start/preview), else fall back to dev."""
    try:
        scripts = (json.loads((app / "package.json").read_text()).get("scripts") or {})
    except Exception:  # noqa: BLE001
        return None, None
    built = any((app / d).is_dir()
                for d in (".next", ".open-next", "dist", "build", ".vercel/output"))
    order = ["start", "preview", "dev"] if built else ["dev", "preview", "start"]
    for s in order:
        if s in scripts:
            return f"npm run {s}", s
    return None, None


def _start_server(app: Path, start_timeout: float) -> Optional[tuple[subprocess.Popen[str], int, str]]:
    """Launch the app on a FORCED free port (via PORT env) so it never collides
    with whatever holds the framework default (:3000). Detect the actual port from
    the boot banner, falling back to the forced port if the server is up but quiet.
    Returns (proc, port, script) or None. Runs in its own session so the whole
    npm→node tree can be torn down by process-group signal."""
    cmd, script = _pick_start_cmd(app)
    if not cmd:
        return None
    port_hint = _free_port()
    env = _env()
    env["PORT"] = str(port_hint)  # Next.js (next dev/start) honors PORT
    proc = subprocess.Popen(
        ["bash", "-lc", f"{cmd} 2>&1"], cwd=str(app), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        start_new_session=True,
    )
    buf: list[str] = []

    def _reader() -> None:
        try:
            for line in proc.stdout:  # type: ignore[union-attr]
                buf.append(line)
        except Exception:  # noqa: BLE001
            pass

    Thread(target=_reader, daemon=True).start()

    # Watch for the boot banner, but only briefly — if the server is alive but
    # hasn't printed a parseable URL, trust the PORT we forced.
    banner_deadline = time.monotonic() + min(start_timeout, 30.0)
    port: Optional[int] = None
    while time.monotonic() < banner_deadline and port is None:
        for line in list(buf):
            m = _URL_RE.search(line)
            if m:
                port = int(m.group(1))
                break
        if port is None:
            if proc.poll() is not None:  # server died before announcing a URL
                break
            time.sleep(0.2)
    if port is None:
        if proc.poll() is not None:
            _stop(proc)  # the server process actually exited (e.g. a real crash)
            return None
        port = port_hint  # up but quiet → trust the forced PORT (validated by _wait_ready)
    return proc, port, script  # type: ignore[return-value]


def _stop(proc: subprocess.Popen[str]) -> None:
    """Thin alias — the implementation moved to area._util so the agent verifier and
    the dashboard kill switch share exactly this teardown."""
    kill_process_group(proc)


def _wait_ready(url: str, timeout: float) -> bool:
    """Poll until the server returns ANY HTTP response (first dev request compiles,
    so a 4xx/5xx still means 'up'). Connection refused → keep waiting."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = max(1.0, deadline - time.monotonic())
        try:
            with urllib.request.urlopen(url, timeout=min(30.0, remaining)) as r:
                r.read(64)
            return True
        except urllib.error.HTTPError:
            return True  # server responded (with an error status) → it's up
        except Exception:  # noqa: BLE001  (URLError / connection refused / reset)
            time.sleep(0.4)
    return False


def _fire_load(url: str, total: int, concurrency: int,
               req_timeout: float) -> dict[str, float]:
    """Fire `total` GETs, up to `concurrency` in flight; measure latency + errors."""
    def _one(_i: int) -> tuple[float, bool]:
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(url, timeout=req_timeout) as r:
                r.read()
                ok = 200 <= r.status < 400
            return (time.monotonic() - t0) * 1000.0, ok
        except urllib.error.HTTPError as e:
            return (time.monotonic() - t0) * 1000.0, 200 <= e.code < 400
        except Exception:  # noqa: BLE001
            return (time.monotonic() - t0) * 1000.0, False

    lat: list[float] = []
    errors = 0
    wall0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=max(1, min(concurrency, total))) as ex:
        for ms, ok in ex.map(_one, range(total)):
            lat.append(ms)
            if not ok:
                errors += 1
    wall = max(1e-6, time.monotonic() - wall0)
    lat.sort()
    return {
        "p50_ms": round(percentile(lat, 50), 1),
        "p95_ms": round(percentile(lat, 95), 1),
        "p99_ms": round(percentile(lat, 99), 1),
        "error_rate_pct": round(100.0 * errors / total, 2),
        "throughput_rps": round(total / wall, 1),
    }


def measure(app_dir: str | Path, *, path: str = "/", total: int = 200,
            concurrency: int = 10, start_timeout: float = 60.0,
            req_timeout: float = 30.0,
            warmup: int = 5) -> tuple[dict[str, float], Optional[str]]:
    """Boot the built app, warm it up, then fire load. Returns (metrics, skip_reason).
    metrics is {} with a reason when the app could not be booted/reached."""
    app = Path(app_dir)
    if total <= 0:
        return {}, "no requests requested"
    srv = _start_server(app, start_timeout)
    if not srv:
        return {}, "no runnable server script / app did not announce a port"
    proc, port, script = srv
    base = f"http://127.0.0.1:{port}{path if path.startswith('/') else '/' + path}"
    try:
        if not _wait_ready(base, start_timeout):
            return {}, f"server ({script}) booted on :{port} but never became ready"
        for _ in range(max(0, warmup)):  # absorb first-request compile (dev)
            try:
                with urllib.request.urlopen(base, timeout=req_timeout) as r:
                    r.read()
            except Exception:  # noqa: BLE001
                break
        m = _fire_load(base, total, concurrency, req_timeout)
        m["_server"] = script  # type: ignore[assignment]  # str provenance in an otherwise-float dict; filtered out before gating
        return m, None
    finally:
        _stop(proc)


def perf_verify(name: str, *, backend: str = "acp", model: Optional[str] = None,
                strict: bool = False, total: int = 200, concurrency: int = 10,
                path: str = "/", start_timeout: float = 60.0,
                root: Optional[Path] = None) -> bool:
    """Load-test the built app against its perf budget. Returns True on pass, when
    advisory, or when the app could not be measured (skip). False only on a blocking
    budget breach. backend/model are accepted for gate-dispatch uniformity (unused —
    this gate drives no agent)."""
    name = safe_name(name)
    root = Path(root) if root else WORKSPACE
    app = root / "apps" / name
    if not app.exists():
        raise RuntimeError(f"no app at {app}")

    budget, blocking = load_budget(name, strict=strict, root=root)
    metrics, skip = measure(app, path=path, total=total, concurrency=concurrency,
                            start_timeout=start_timeout)
    # A COMMITTED budget (specs/<name>/perf.yaml, or --strict) that could NOT be
    # measured must not silently pass — it is a guarantee we failed to verify, and the
    # commonest reason is that the app's server never came up, which is exactly what a
    # perf gate is supposed to notice. `nfr` already does this; `perf` returned True
    # before it ever consulted `blocking`.
    if not metrics:
        if blocking:
            print(f"[area] perf: FAIL — a committed budget could not be measured "
                  f"({skip}) — not silently passing")
            return False
        print(f"[area] perf: could not measure ({skip}) — skipped (advisory)")
        return True

    server = metrics.get("_server", "?")
    gated = {k: v for k, v in metrics.items() if not str(k).startswith("_")}
    results = evaluate(gated, budget)
    print(f"[area] perf: {total} reqs @ concurrency {concurrency} via "
          f"`npm run {server}`")
    if not results:
        if blocking:
            print("[area] perf: FAIL — committed budget(s) "
                  f"{sorted(budget)} matched no measured metric — not silently passing")
            return False
        print("[area] perf: no budgeted metrics measured — skipped (advisory)")
        return True
    for r in results:
        arrow = "≥" if r["floor"] else "≤"
        print(f"[area] perf {r['metric']}: {r['value']} (budget {arrow} {r['limit']}) "
              f"{'OK' if r['ok'] else 'OVER'}")
    breaches = [r for r in results if not r["ok"]]
    if not breaches:
        print(f"[area] perf: PASS ({len(results)} metric(s) within budget)")
        return True
    if blocking:
        print(f"[area] perf: FAIL — {len(breaches)} metric(s) out of budget")
        return False
    print(f"[area] perf: {len(breaches)} out of budget (ADVISORY — commit "
          f"specs/{name}/perf.yaml or pass --strict to make this block)")
    return True
