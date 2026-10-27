"""area.evals — grade changes to the FACTORY, not to an app.

AREA's rule is "never let the same reasoning write AND grade". Applied to AREA
itself, it says: when a prompt, a skill or a knob changes, something independent must
measure whether that helped. Nothing did. `obs.summary()` reported cost and
determinism, but no run was tied to the configuration that produced it, so every
factory change was adopted on vibes.

With `area.profile` stamping a (kind, digest) onto each run, this module answers the
question the reference architecture asks before promoting a change: *"do evals and run
metrics show the change improves outcomes or introduces regressions?"* (The Secure
Software Factory, p.19).

HOW IT JUDGES — regression against the PREVIOUS version of the same kind, which is
Tung's chosen rule. `current` is the profile's digest as it stands right now, so the
moment you edit a prompt the current version has zero measured runs and the verdict is
`insufficient-data`: the honest answer, and the reason the gate is advisory by default.

WHAT IT CANNOT DO: attribute history. Runs recorded before profiles existed carry a
null digest and are reported as `unattributed` rather than silently folded into a
baseline — we do not know which prompt produced them.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

# Per side. Below this, say "insufficient-data" instead of reading noise as a trend:
# the measured baseline is first-try 0.91 over 68 convergence runs, so a 2-run sample
# can swing the rate by half.
MIN_RUNS = 5

# What counts as a regression. Calibrated against the only real numbers AREA has
# (110 runs: first-try 0.91, avg 1.12 attempts, $1.65/run), not invented round
# numbers: a 0.10 drop in first-try rate is ~1 run in 10 going from clean to retried.
TOLERANCE: dict[str, float] = {
    "first_try_rate": -0.10,   # absolute drop worse than this = regression
    "pass_rate": -0.10,        # absolute drop
    "avg_iters": 0.25,         # absolute rise in attempts
    "avg_cost_usd": 0.25,      # RELATIVE rise (25% more expensive)
}
_RELATIVE = {"avg_cost_usd"}
_LOWER_IS_BETTER = {"avg_iters", "avg_cost_usd"}


def metrics(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Outcome metrics for one set of runs. `None` where it cannot be computed —
    never 0, which would read as a measured zero."""
    n = len(runs)
    conv = [r for r in runs if isinstance(r.get("outer_iters"), int)]
    costed = [r["cost_usd"] for r in runs if r.get("cost_usd") is not None]
    judged = [r for r in runs if r.get("passed") is not None]
    first = sum(1 for r in conv if r["outer_iters"] == 1 and r.get("passed"))
    return {
        "n": n,
        "convergence_runs": len(conv),
        "pass_rate": round(sum(1 for r in judged if r["passed"]) / len(judged), 3)
        if judged else None,
        "first_try_rate": round(first / len(conv), 3) if conv else None,
        "avg_iters": round(sum(r["outer_iters"] for r in conv) / len(conv), 3)
        if conv else None,
        "avg_cost_usd": round(sum(costed) / len(costed), 4) if costed else None,
    }


def _runs_for(kind: str, runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Runs this profile stamped itself onto."""
    return [r for r in runs if r.get("profile") == kind]


def _legacy_runs_for(prof: Any, runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Runs that belong to this kind BY LABEL but carry no digest — recorded before
    profiles existed.

    Counting these matters: without it the report said "no runs recorded" for every
    kind while 110 real runs sat in the log, which reads as "nothing has ever run"
    rather than the truth, "nothing is attributable yet"."""
    out = []
    for r in runs:
        if r.get("profile_digest"):
            continue
        label = r.get("label")
        if isinstance(label, str) and prof.owns(label):
            out.append(r)
    return out


def versions(kind: str, runs: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    """Attributed digests for a kind, oldest first by the run that introduced them.
    Runs with a null digest (recorded before profiles existed) are excluded."""
    seen: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for r in sorted(_runs_for(kind, runs), key=lambda r: r.get("ts") or 0):
        dig = r.get("profile_digest")
        if not dig:
            continue
        if dig not in seen:
            seen[dig] = []
            order.append(dig)
        seen[dig].append(r)
    return [(d, seen[d]) for d in order]


def _delta(metric: str, cur: Optional[float], prev: Optional[float],
           ) -> tuple[Optional[float], bool]:
    """(delta, regressed). Delta is relative for cost, absolute otherwise."""
    if cur is None or prev is None:
        return None, False
    if metric in _RELATIVE:
        d = (cur - prev) / prev if prev else 0.0
    else:
        d = cur - prev
    tol = TOLERANCE[metric]
    regressed = d > tol if metric in _LOWER_IS_BETTER else d < tol
    return round(d, 4), regressed


def compare(kind: str, *, runs: Optional[list[dict[str, Any]]] = None,
            min_runs: int = MIN_RUNS, root: Optional[Path] = None) -> dict[str, Any]:
    """Grade this kind's CURRENT profile version against the previous one."""
    from area import obs
    from area.profile import load_profile

    all_runs = obs.load_runs() if runs is None else runs
    prof = load_profile(kind, root=root)
    if prof is None:
        return {"kind": kind, "verdict": "no-profile",
                "reason": f"no profiles/{kind}.yaml"}
    current_digest = prof.digest
    mine = _runs_for(kind, all_runs)
    legacy = _legacy_runs_for(prof, all_runs)
    unattributed = len(legacy)
    vers = versions(kind, all_runs)
    cur_runs = next((rs for d, rs in vers if d == current_digest), [])
    prev_digest = next((d for d, _ in reversed(vers) if d != current_digest), None)
    prev_runs = next((rs for d, rs in vers if d == prev_digest), []) if prev_digest else []

    out: dict[str, Any] = {
        "kind": kind,
        "current_digest": current_digest,
        "previous_digest": prev_digest,
        "current": metrics(cur_runs),
        "previous": metrics(prev_runs),
        "unattributed_runs": unattributed,
        "deltas": {},
    }
    if not mine:
        out.update(verdict="no-data", reason=(
            f"no attributed runs for '{kind}' yet"
            + (f" ({unattributed} older run(s) match by label but predate profiles, "
               "so they cannot be a baseline)" if unattributed
               else "; this kind has never run")))
        return out
    if prev_digest is None:
        out.update(verdict="new-profile", reason=(
            f"only one measured version so far ({len(cur_runs)} run(s)); nothing to "
            "compare against"
            + (f"; {unattributed} older run(s) predate profiles and cannot be "
               "attributed" if unattributed else "")))
        return out
    if len(cur_runs) < min_runs or len(prev_runs) < min_runs:
        out.update(verdict="insufficient-data", reason=(
            f"need >={min_runs} runs per version to judge "
            f"(current {len(cur_runs)}, previous {len(prev_runs)})"))
        return out

    regressions: list[str] = []
    improvements: list[str] = []
    for m in TOLERANCE:
        d, bad = _delta(m, out["current"].get(m), out["previous"].get(m))
        out["deltas"][m] = d
        if d is None:
            continue
        if bad:
            regressions.append(m)
        elif (d > 0) is (m not in _LOWER_IS_BETTER) and d != 0:
            improvements.append(m)
    if regressions:
        out.update(verdict="regressed",
                   reason="worse than the previous version: " + ", ".join(regressions))
    else:
        out.update(verdict="improved" if improvements else "ok",
                   reason=("better on: " + ", ".join(improvements)) if improvements
                   else "within tolerance of the previous version")
    return out


def check(kinds: Optional[list[str]] = None, *, strict: bool = False,
          runs: Optional[list[dict[str, Any]]] = None,
          root: Optional[Path] = None) -> tuple[bool, list[dict[str, Any]]]:
    """(ok, results). A regression always fails. A broken profile always fails — it
    silently stops attributing runs. "insufficient-data"/"no-data" pass unless strict,
    because a gate that cannot measure must not pretend to have measured."""
    from area.profile import all_profiles, broken_profiles

    broken = broken_profiles(root=root)
    names = kinds or sorted(all_profiles(root=root))
    results = [compare(k, runs=runs, root=root) for k in names]
    for name, why in broken.items():
        results.append({"kind": name, "verdict": "broken", "reason": why})
    bad = {"regressed", "broken"}
    if strict:
        bad |= {"insufficient-data", "no-data", "no-profile"}
    return (not any(r["verdict"] in bad for r in results)), results


_ICON = {"ok": "✅", "improved": "🎉", "regressed": "❌", "broken": "💥",
         "insufficient-data": "…", "no-data": "–", "new-profile": "🆕",
         "no-profile": "?"}


def report_text(results: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for r in sorted(results, key=lambda r: (r["verdict"] != "regressed", r["kind"])):
        lines.append(f"  {_ICON.get(r['verdict'], ' ')} {r['kind']:24s} "
                     f"{r['verdict']:18s} {r.get('reason', '')}")
        cur, prev = r.get("current"), r.get("previous")
        if r["verdict"] in ("regressed", "improved", "ok") and cur and prev:
            for m, d in (r.get("deltas") or {}).items():
                if d is None:
                    continue
                unit = "%" if m in _RELATIVE else ""
                shown = round(d * 100, 1) if m in _RELATIVE else d
                lines.append(f"        {m:16s} {prev.get(m)} -> {cur.get(m)} "
                             f"({shown:+}{unit})")
    return "\n".join(lines)
