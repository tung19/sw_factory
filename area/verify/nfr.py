"""area.verify.nfr — deterministic performance / NFR budget gate (PR4, §11).

The other gates drive an agent; this one MEASURES the built app and blocks on
budget breaches, so it is deterministic and CI-friendly (no live load test, no
agent). Metrics are static: shipped build-output size, production dependency
count, node_modules install weight, and (optionally) a clean-build time.

Budgets follow AREA's oracle philosophy — a budget the USER supplied is part of
the oracle, so it BLOCKS; a guessed default is ADVISORY (reports, never fails)
unless --strict, mirroring the audit tier-2 posture:
  - workspace/specs/<name>/nfr.yaml present  → its budgets BLOCK
  - no nfr.yaml                               → defaults, advisory (or --strict)

nfr.yaml is a flat `metric: number` map, e.g.:
    bundle_kib: 2048
    dep_count: 25
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

from area._util import safe_name
from area.engine import scrubbed_env
from area.paths import WORKSPACE  # noqa: E402 (leaf single-source; avoids importing the whole pipeline+SDK behind a gate)

# Shipped build-output dirs to measure (first existing wins). Cache subdirs are
# excluded — they are not part of what ships / cold-starts.
_BUILD_DIRS = (".open-next", ".vercel/output", ".next", "dist", "build")
_EXCLUDE_PARTS = ("cache",)

# Guessed, lenient defaults (advisory unless the user commits real budgets).
DEFAULT_BUDGET: dict[str, int] = {
    "bundle_kib": 5120,       # 5 MiB of shipped build output
    "dep_count": 40,          # production dependencies
    "node_modules_mib": 700,  # install weight
    "build_ms": 180_000,      # 3 min clean build (only measured with run_build)
}


def _env() -> dict[str, str]:
    # Built on `scrubbed_env()`, not `os.environ`: every command this module launches
    # runs the GENERATED app — agent-authored package.json scripts, so arbitrary
    # `postinstall`/build code — and must not inherit the deploy/cloud tokens this
    # process holds. Only those named keys are dropped; npm/node configuration and PATH
    # are preserved, which is what keeps the build working.
    e = scrubbed_env()
    e.setdefault("npm_config_cache", str(Path.home() / ".cache" / "npm-area"))
    return e


def _dir_size(d: Path, exclude: tuple[str, ...] = ()) -> int:
    total = 0
    for p in d.rglob("*"):
        if not p.is_file():
            continue
        if any(x in p.parts for x in exclude):
            continue
        try:
            total += p.stat().st_size
        except OSError:
            pass
    return total


def _bundle_bytes(app: Path) -> Optional[int]:
    for rel in _BUILD_DIRS:
        d = app / rel
        if d.is_dir():
            return _dir_size(d, exclude=_EXCLUDE_PARTS)
    return None


def _dep_count(app: Path) -> Optional[int]:
    try:
        pkg = json.loads((app / "package.json").read_text())
        return len(pkg.get("dependencies") or {})
    except Exception:  # noqa: BLE001
        return None


def parse_budget_yaml(text: str) -> dict[str, float]:
    """Parse a flat `metric: number` budget map. Ignores comments, blanks, and
    any non-numeric value (so a stray line can't silently disable a metric)."""
    out: dict[str, float] = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        k, _, v = line.partition(":")
        k, v = k.strip(), v.strip()
        try:
            num = float(v)
        except ValueError:
            continue
        out[k] = int(num) if num.is_integer() else num
    return out


def measure(app_dir: str | Path, *, run_build: bool = False,
            build_cmd: str = "npm run build") -> dict[str, float]:
    """Gather deterministic NFR metrics from a BUILT app. With run_build, also run
    a clean timed build to measure build_ms (and refresh the output measured)."""
    app = Path(app_dir)
    m: dict[str, float] = {}
    if run_build:
        t0 = time.monotonic()
        bp = subprocess.run(["bash", "-lc", f"{build_cmd} 2>&1"], cwd=str(app),
                            capture_output=True, text=True, env=_env())
        m["build_ms"] = int((time.monotonic() - t0) * 1000)
        if bp.returncode != 0:
            # don't silently time + measure a FAILED build as if it were fine
            print("[area] nfr: ⚠ --nfr-build timing is off — the build FAILED "
                  f"(rc={bp.returncode}); bundle metrics may be stale/partial.")
    b = _bundle_bytes(app)
    if b is not None:
        m["bundle_kib"] = b // 1024
    dc = _dep_count(app)
    if dc is not None:
        m["dep_count"] = dc
    nm = app / "node_modules"
    if nm.is_dir():
        m["node_modules_mib"] = _dir_size(nm) // (1024 * 1024)
    return m


def evaluate(metrics: dict[str, float], budget: dict[str, float]) -> list[dict[str, Any]]:
    """Per-metric verdicts. Only metrics present in BOTH the measurement and the
    budget are gated (a budget for an unmeasured metric is simply skipped)."""
    out: list[dict[str, Any]] = []
    for k, limit in budget.items():
        if k not in metrics:
            continue
        v = metrics[k]
        out.append({"metric": k, "value": v, "limit": limit, "ok": v <= limit})
    return out


def load_budget(name: str, *, strict: bool = False,
                root: Optional[Path] = None) -> tuple[dict[str, float], bool]:
    """Return (budget, blocking). A spec-level nfr.yaml means the user committed
    real budgets → blocking; otherwise defaults, advisory unless --strict."""
    root = Path(root) if root else WORKSPACE
    nfr = root / "specs" / name / "nfr.yaml"
    budget: dict[str, float] = dict(DEFAULT_BUDGET)
    blocking = strict
    if nfr.exists():
        blocking = True
        budget.update(parse_budget_yaml(nfr.read_text()))
    return budget, blocking


def nfr_verify(name: str, *, backend: str = "acp", model: Optional[str] = None,
               strict: bool = False, run_build: bool = False,
               root: Optional[Path] = None) -> bool:
    """Measure the built app against its NFR budget. Returns True on pass (or when
    advisory). backend/model are accepted for gate-dispatch uniformity but unused —
    the gate is deterministic."""
    name = safe_name(name)
    root = Path(root) if root else WORKSPACE
    app = root / "apps" / name
    if not app.exists():
        raise RuntimeError(f"no app at {app}")

    budget, blocking = load_budget(name, strict=strict, root=root)
    metrics = measure(app, run_build=run_build)
    results = evaluate(metrics, budget)

    # A COMMITTED (user nfr.yaml) budget whose metric produced NO measurement must
    # not silently pass — it's a committed guarantee we couldn't verify (e.g. an
    # unrecognised build-output layout). When blocking, FAIL loudly.
    nfr_yaml = (Path(root) if root else WORKSPACE) / "specs" / name / "nfr.yaml"
    committed = parse_budget_yaml(nfr_yaml.read_text()) if nfr_yaml.exists() else {}
    unmeasured = [k for k in committed if k not in metrics]
    if blocking and unmeasured:
        print(f"[area] nfr: FAIL — committed budget(s) {unmeasured} could not be "
              "measured (no build output / unknown layout?) — not silently passing")
        return False

    if not results:
        print("[area] nfr: no measurable metrics (no build output?) — skipped")
        return True
    for r in results:
        print(f"[area] nfr {r['metric']}: {r['value']} / {r['limit']} "
              f"{'OK' if r['ok'] else 'OVER'}")
    breaches = [r for r in results if not r["ok"]]
    if not breaches:
        print(f"[area] nfr: PASS ({len(results)} metric(s) within budget)")
        return True
    if blocking:
        print(f"[area] nfr: FAIL — {len(breaches)} metric(s) over budget")
        return False
    print(f"[area] nfr: {len(breaches)} over budget (ADVISORY — commit "
          f"specs/{name}/nfr.yaml or pass --strict to make this block)")
    return True
