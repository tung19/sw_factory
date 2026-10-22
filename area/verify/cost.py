"""area.verify.cost — hard cost-cap gate (PR3, §11).

`--budget` is a SOFT per-run cap: the SDK stops ONE `agent.run()` at
`max_budget_per_run`. But a build RETRIES (run_until loops, re-authoring the
holdout, re-adjudication), so the TOTAL spend of a build can be several times
any single run's cap. This gate is the HARD cap: it sums the USD cost of every
agent run in this build (from `area.obs`) and FAILS — blocking the deploy — if
the total exceeds the budget.

Oracle posture (like nfr/perf): a budget the user commits in
`workspace/specs/<name>/cost.yaml` (`max_usd: <N>`) is part of the oracle and
BLOCKS; a guessed `DEFAULT_MAX_USD` is ADVISORY (reports, never fails) unless
`--strict` (or an explicit `--cost-max`, which is the user's number, so it
blocks too).

HONEST SCOPE: cost comes from `area.obs`'s `runs.jsonl`, a global, per-run log
that is NOT tagged by app. The enforcement path (the gate running right after a
build) is precise — it sums runs since the build started (the CLI stamps
`args._build_start`). The standalone `area cost <name>` has no build context, so
it sums the most-recent build SESSION by a time-gap heuristic (the trailing
cluster of runs less than SESSION_GAP_S apart) — an approximate view, not a
per-app ledger. A run with no recorded cost (keyless / agent-free) yields $0 and
the gate SKIPS (it never blocks a build it cannot measure).

cost.yaml is a flat `metric: number` map (reusing the nfr parser):
    max_usd: 8
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from area._util import safe_name
from area.obs import load_runs
from area.paths import WORKSPACE
from area.verify.nfr import parse_budget_yaml

DEFAULT_MAX_USD = 15.0   # advisory ceiling unless cost.yaml / --cost-max commits one
SESSION_GAP_S = 1800.0   # runs > 30 min apart belong to different build sessions


def build_cost(*, since: Optional[float] = None,
               runs: Optional[list[dict[str, Any]]] = None) -> float:
    """Total USD cost of this build's agent runs (from area.obs).

    since: sum runs with ts >= since — precise (the build's own window).
    else:  sum the most-recent build session — the trailing cluster of runs
           within SESSION_GAP_S of each other (the approximate standalone view).
    """
    rows = load_runs() if runs is None else runs
    costed = [r for r in rows
              if r.get("cost_usd") is not None and r.get("ts") is not None]
    if since is not None:
        return round(sum(float(r["cost_usd"]) for r in costed
                         if float(r["ts"]) >= since), 4)
    if not costed:
        return 0.0
    costed.sort(key=lambda r: float(r["ts"]))
    total = float(costed[-1]["cost_usd"])
    prev = float(costed[-1]["ts"])
    for r in reversed(costed[:-1]):
        ts = float(r["ts"])
        if prev - ts > SESSION_GAP_S:
            break
        total += float(r["cost_usd"])
        prev = ts
    return round(total, 4)


def load_cap(name: str, *, strict: bool, override: Optional[float] = None,
             root: Optional[Path] = None) -> tuple[float, bool]:
    """Return (max_usd, blocking). An explicit --cost-max override or a committed
    cost.yaml is the user's number and BLOCKS; the default is advisory unless
    strict."""
    if override is not None:
        return override, True
    base = root or WORKSPACE
    p = base / "specs" / safe_name(name) / "cost.yaml"
    if p.exists():
        budget = parse_budget_yaml(p.read_text())
        if "max_usd" in budget:
            return budget["max_usd"], True
    return DEFAULT_MAX_USD, strict


def cost_verify(name: str, *, backend: str = "acp", model: Optional[str] = None,
                strict: bool = False, override: Optional[float] = None,
                since: Optional[float] = None,
                root: Optional[Path] = None) -> bool:
    """Gate: total build spend must be <= the budget. Returns True on pass, on an
    ADVISORY breach, or when no cost was recorded; False only on a BLOCKING
    breach. backend/model are accepted for dispatch uniformity (unused)."""
    cap, blocking = load_cap(name, strict=strict, override=override, root=root)
    spent = build_cost(since=since)
    if spent <= 0:
        print("[cost] no agent cost recorded (keyless / agent-free run) — skipping")
        return True
    ok = spent <= cap
    tag = "BLOCKING" if blocking else "advisory"
    print(f"[cost] ${spent:.4f} spent / ${cap:.2f} cap ({tag}) — "
          f"{'ok' if ok else 'OVER'}")
    if ok:
        return True
    if blocking:
        print(f"[cost] ❌ build spent ${spent:.4f} > ${cap:.2f} budget — blocking deploy")
        return False
    print(f"[cost] ⚠ over the default ${cap:.2f} ceiling (advisory). Commit "
          f"specs/{safe_name(name)}/cost.yaml (`max_usd:`) or pass --strict / "
          f"--cost-max to enforce.")
    return True
