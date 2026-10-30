"""area.obs — lightweight observability: cost / latency / outcome per agent run.

Leaf module (imports nothing from area) to avoid cycles. Each agent run appends
one line to workspace/.area/runs.jsonl; `area obs` aggregates it.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Optional

from area.paths import WORKSPACE  # zero-dep constant module (no cycle risk)

RUNS = WORKSPACE / ".area" / "runs.jsonl"
# The production ledger path, captured at import before any test monkeypatches RUNS.
# The write guard below uses it to tell "a test forgot to redirect RUNS" (block) from
# "a test redirected RUNS to a tmp path" (allow).
_DEFAULT_RUNS = RUNS


def _under_test() -> bool:
    """True inside a pytest run (pytest always sets PYTEST_CURRENT_TEST)."""
    return "PYTEST_CURRENT_TEST" in os.environ

# The app whose build is currently running, stamped onto each run record so a
# per-app gate (area.verify.cost) can scope spend to ONE app even though
# runs.jsonl is a single shared log and concurrent builds run as separate
# processes appending to it. Set once per build by the pipeline entrypoints.
_current_app: Optional[str] = None


def set_app(name: Optional[str]) -> None:
    """Tag subsequent `log_run` records with this app name (per-process)."""
    global _current_app
    _current_app = name


# (kind, digest) per obs label, resolved once per process. Computing a digest imports
# the prompt-owning modules and hashes their source, so it must not happen per run.
_profile_cache: dict[str, tuple[Optional[str], Optional[str]]] = {}


def profile_of(label: str) -> tuple[Optional[str], Optional[str]]:
    """(kind, digest) for an obs label — how a run is attributed to the factory
    configuration that produced it. Without this, 110 recorded runs could not be tied
    to any prompt/skill/knob version, so a factory change was ungradeable.

    Best-effort: attribution must never break a run, and a label no profile claims
    simply records nulls."""
    if label in _profile_cache:
        return _profile_cache[label]
    kind: Optional[str] = None
    dig: Optional[str] = None
    try:
        from area.profile import defaults_for

        kind, dig, _ = defaults_for(label)
    except Exception:  # noqa: BLE001
        pass
    _profile_cache[label] = (kind, dig)
    return kind, dig


def cost_of(conv: Any) -> Optional[float]:
    """Best-effort accumulated USD cost of a conversation."""
    try:
        return float(conv.conversation_stats.get_combined_metrics().accumulated_cost)
    except Exception:
        pass
    try:
        return float(conv.agent.llm.metrics.accumulated_cost)
    except Exception:
        return None



# What the run ACTUALLY had, not what its profile implies.
#
# M9-1b scoped the profile digest so a Cloudflare skill stops re-versioning the kinds a
# Cloudflare build never involves. That left a residual, recorded at the time: the digest
# is derived from the PROFILE, so an `inherited` kind running in a Cloudflare app and the
# same kind running in a plain app now carry the SAME version while seeing different
# packs. Measured on this machine: `apps/taskboard/.claude/skills/` holds
# area-oracle-loop + vinext-cf-build (built before target scoping) and
# `apps/expenses/` holds area-oracle-loop alone — two different packs, indistinguishable
# in the ledger.
#
# `area evals` would then compare runs that had different domain knowledge as if the only
# difference were the thing under test. Closing this is a prerequisite for F4 being worth
# its ~$40-50 of builds, not a tidy-up.
_skills_cache: dict[str, tuple[Optional[str], tuple[str, ...]]] = {}


def installed_skills(name: Optional[str]) -> tuple[Optional[str], tuple[str, ...]]:
    """(digest, names) of the skill pack present in this app, or (None, ()).

    Reads `<app>/.claude/skills/`, which is where `area.skills.install_skills` puts it.
    None means there is nothing to read — a `spec` run happens before the app exists,
    and that is information, not a gap. Memoised per process: one shallow walk of two
    small directories, but `log_run` is called on every agent run.
    """
    if not name:
        return (None, ())
    if name in _skills_cache:
        return _skills_cache[name]
    import hashlib

    d = WORKSPACE / "apps" / name / ".claude" / "skills"
    out: tuple[Optional[str], tuple[str, ...]] = (None, ())
    try:
        if d.is_dir():
            names = sorted(p.name for p in d.iterdir() if (p / "SKILL.md").is_file())
            if names:
                h = hashlib.sha256()
                for n in names:
                    h.update(n.encode())
                    h.update(b"\0")
                    # Hash the WHOLE skill subtree, not just SKILL.md (B12): a skill's
                    # references/ and vendored scripts ARE domain knowledge, and
                    # profile._pack_digest already covers them — so "what a run had"
                    # must track "what can change this kind", or evals' confounded-skills
                    # guard is blind to an intra-skill change.
                    for f in sorted((d / n).rglob("*")):
                        if not f.is_file():
                            continue
                        h.update(str(f.relative_to(d / n)).encode())
                        h.update(b"\0")
                        try:
                            h.update(f.read_bytes())
                        except OSError:
                            h.update(b"<unreadable>")
                        h.update(b"\0")
                out = ("sha256:" + h.hexdigest()[:16], tuple(names))
    except OSError:
        pass
    # Only memoize a REAL pack. A `spec` run calls this before the build stage
    # installs `.claude/skills/`; caching that (None, ()) miss poisoned every
    # later build-stage run's attribution (B5). A miss re-stats next time.
    if out[0] is not None:
        _skills_cache[name] = out
    return out

def log_run(
    label: str,
    *,
    duration: float,
    cost: Optional[float] = None,
    outer_iters: Optional[int] = None,
    passed: Optional[bool] = None,
    backend: Optional[str] = None,
    name: Optional[str] = None,
) -> None:
    RUNS.parent.mkdir(parents=True, exist_ok=True)
    prof_kind, prof_digest = profile_of(label)
    skills_d, skills_n = installed_skills(name if name is not None else _current_app)
    rec = {
        "ts": time.time(),
        "label": label,
        "name": name if name is not None else _current_app,
        "duration_s": round(duration, 2),
        "cost_usd": cost,
        "outer_iters": outer_iters,
        "passed": passed,
        "backend": backend,
        # which version of this kind's configuration produced the run (area.profile)
        "profile": prof_kind,
        "profile_digest": prof_digest,
        # and which domain knowledge it ACTUALLY had — see installed_skills
        "skills_digest": skills_d,
        "skills": list(skills_n),
    }
    # Defense-in-depth (from superpowers:systematic-debugging/defense-in-depth): a test that
    # forgot to redirect RUNS must not pollute the real ledger — the 108-fake-rows bug. Under
    # pytest, skip writing the PRODUCTION ledger unless explicitly opted in; a test that
    # monkeypatched RUNS to a tmp path (RUNS != _DEFAULT_RUNS) still writes normally.
    skip_write = (_under_test() and RUNS == _DEFAULT_RUNS
                  and os.environ.get("AREA_OBS_ALLOW_WRITE") != "1")
    if not skip_write:
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


def load_runs() -> list[dict[str, Any]]:
    runs = []
    if RUNS.exists():
        for line in RUNS.read_text(errors="ignore").splitlines():
            try:
                runs.append(json.loads(line))
            except Exception:
                pass
    return runs


def summary(runs: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    """Aggregate agent runs: cost/latency per stage PLUS determinism metrics.

    Determinism comes from `outer_iters` — the attempt a convergence loop
    (run_until) went green on: 1 = first-try, >1 = needed retries, and a
    not-passed run that reached the cap = failed to converge. Runs with a null
    `outer_iters` (run_once, e.g. authoring) have no convergence loop and are
    excluded from the determinism rates.
    """
    runs = load_runs() if runs is None else runs
    by_label: dict[str, dict[str, Any]] = {}
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
        # A run with no cost is UNKNOWN, not $0 — disclose the count so total_cost_usd
        # reads as a lower bound rather than silently folding unknowns into zero.
        "runs_missing_cost": sum(1 for r in runs if r.get("cost_usd") is None),
        "convergence_runs": conv_n,
        "first_try_rate": round(first_try / conv_n, 3) if conv_n else None,
        "retry_rate": round(retried / conv_n, 3) if conv_n else None,
        "avg_iters": round(sum(r["outer_iters"] for r in conv) / conv_n, 2) if conv_n else None,
        "by_label": by_label,
    }
