"""area.obs — lightweight observability: cost / latency / outcome per agent run.

Leaf module (imports nothing from area) to avoid cycles. Each agent run appends
one line to workspace/.area/runs.jsonl; `area obs` aggregates it.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from area.paths import WORKSPACE  # zero-dep constant module (no cycle risk)

RUNS = WORKSPACE / ".area" / "runs.jsonl"


def cost_of(conv) -> Optional[float]:
    """Best-effort accumulated USD cost of a conversation."""
    try:
        return float(conv.conversation_stats.get_combined_metrics().accumulated_cost)
    except Exception:
        pass
    try:
        return float(conv.agent.llm.metrics.accumulated_cost)
    except Exception:
        return None


def log_run(
    label: str,
    *,
    duration: float,
    cost: Optional[float] = None,
    outer_iters: Optional[int] = None,
    passed: Optional[bool] = None,
    backend: Optional[str] = None,
) -> None:
    RUNS.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": time.time(),
        "label": label,
        "duration_s": round(duration, 2),
        "cost_usd": cost,
        "outer_iters": outer_iters,
        "passed": passed,
        "backend": backend,
    }
    try:
        with RUNS.open("a") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass
    c = f"${cost:.4f}" if cost is not None else "$?"
    verdict = "ok" if passed else ("fail" if passed is not None else "-")
    print(f"[obs] {label}: {duration:.1f}s · {c} · {verdict}")
    # Optional: mirror this run as a Langfuse span under the current pipeline.
    try:
        from area import trace

        trace.log_span(label, duration=duration, cost=cost, passed=passed,
                       backend=backend, metadata={"outer_iters": outer_iters})
    except Exception:
        pass


def load_runs() -> list[dict]:
    runs = []
    if RUNS.exists():
        for line in RUNS.read_text(errors="ignore").splitlines():
            try:
                runs.append(json.loads(line))
            except Exception:
                pass
    return runs


def summary(runs: Optional[list[dict]] = None) -> dict:
    """Aggregate agent runs: cost/latency per stage PLUS determinism metrics.

    Determinism comes from `outer_iters` — the attempt a convergence loop
    (run_until) went green on: 1 = first-try, >1 = needed retries, and a
    not-passed run that reached the cap = failed to converge. Runs with a null
    `outer_iters` (run_once, e.g. authoring) have no convergence loop and are
    excluded from the determinism rates.
    """
    runs = load_runs() if runs is None else runs
    by_label: dict = {}
    for r in runs:
        d = by_label.setdefault(
            r.get("label", "?"),
            {"n": 0, "cost": 0.0, "time": 0.0, "ok": 0,
             "conv_n": 0, "iters_sum": 0, "first_try": 0, "retried": 0},
        )
        d["n"] += 1
        d["cost"] += r.get("cost_usd") or 0
        d["time"] += r.get("duration_s") or 0
        passed = bool(r.get("passed"))
        if passed:
            d["ok"] += 1
        it = r.get("outer_iters")
        if isinstance(it, int):
            d["conv_n"] += 1
            d["iters_sum"] += it
            if it == 1 and passed:
                d["first_try"] += 1
            if it > 1:
                d["retried"] += 1
    for d in by_label.values():
        d["avg_cost"] = round(d["cost"] / d["n"], 4) if d["n"] else 0.0
        d["avg_iters"] = round(d["iters_sum"] / d["conv_n"], 2) if d["conv_n"] else None

    conv = [r for r in runs if isinstance(r.get("outer_iters"), int)]
    conv_n = len(conv)
    first_try = sum(1 for r in conv if r["outer_iters"] == 1 and r.get("passed"))
    retried = sum(1 for r in conv if r["outer_iters"] > 1)
    costed = [r["cost_usd"] for r in runs if r.get("cost_usd") is not None]
    return {
        "runs": len(runs),
        "total_cost_usd": round(sum(r.get("cost_usd") or 0 for r in runs), 4),
        "total_time_s": round(sum(r.get("duration_s") or 0 for r in runs), 1),
        "avg_cost_usd": round(sum(costed) / len(costed), 4) if costed else None,
        "convergence_runs": conv_n,
        "first_try_rate": round(first_try / conv_n, 3) if conv_n else None,
        "retry_rate": round(retried / conv_n, 3) if conv_n else None,
        "avg_iters": round(sum(r["outer_iters"] for r in conv) / conv_n, 2) if conv_n else None,
        "by_label": by_label,
    }
