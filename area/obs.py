"""area.obs — lightweight observability: cost / latency / outcome per agent run.

Leaf module (imports nothing from area) to avoid cycles. Each agent run appends
one line to workspace/.area/runs.jsonl; `area obs` aggregates it.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent
RUNS = _ROOT / "workspace" / ".area" / "runs.jsonl"


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


def summary() -> dict:
    runs = []
    if RUNS.exists():
        for line in RUNS.read_text(errors="ignore").splitlines():
            try:
                runs.append(json.loads(line))
            except Exception:
                pass
    by_label: dict = {}
    for r in runs:
        d = by_label.setdefault(
            r.get("label", "?"), {"n": 0, "cost": 0.0, "time": 0.0, "ok": 0}
        )
        d["n"] += 1
        d["cost"] += r.get("cost_usd") or 0
        d["time"] += r.get("duration_s") or 0
        if r.get("passed"):
            d["ok"] += 1
    return {
        "runs": len(runs),
        "total_cost_usd": round(sum(r.get("cost_usd") or 0 for r in runs), 4),
        "total_time_s": round(sum(r.get("duration_s") or 0 for r in runs), 1),
        "by_label": by_label,
    }
