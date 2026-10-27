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

HOW IT COMPARES — MATCHED PAIRS, not aggregates. Two versions that ran on different
work are not comparable: a prompt that looks better may simply have drawn easier
tasks. So a version is graded only on the tasks BOTH versions ran, the way Harness2's
"probe" step runs a candidate on the same task under matched settings
(arXiv:2610.14224). With no shared task the verdict is `unpaired` and nothing is
certified — the deltas are still reported, labelled confounded, because a regression
is worth seeing even when it cannot be attributed.

WHAT IT CANNOT DO: attribute history. Runs recorded before profiles existed carry a
null digest and are reported as `unattributed` rather than silently folded into a
baseline — we do not know which prompt produced them. Do not try to rescue them as
one: that ledger ALSO over-reports passes, because `run_once` used to record
`passed=True` without any verifier (109 of its 110 runs say they passed). Those runs
can tell you about cost and duration; they cannot tell you about outcomes.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

import yaml

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


TASKS_FILE = "evals/tasks.yaml"


def load_task_set(root: Optional[Path] = None) -> Optional[set[str]]:
    """The declared fixed eval set (`evals/tasks.yaml`), or None if absent.

    Names are app names, the key `obs.set_app()` stamps onto every agent run in a
    pipeline. Returning None means "compare on whatever both versions happened to run",
    which is weaker but still paired."""
    import yaml

    from area.paths import REPO

    f = (Path(root) if root else REPO) / TASKS_FILE
    if not f.is_file():
        return None
    try:
        raw = yaml.safe_load(f.read_text()) or {}
        names = {str(t["name"]) for t in raw.get("tasks", []) if t.get("name")}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    return names or None


def _task_of(run: dict[str, Any]) -> Optional[str]:
    """Which task a run was on. `obs` stamps the app name, which IS the unit of work
    for every agent kind. None when nothing was recorded — such a run cannot be paired."""
    t = run.get("name")
    return str(t) if t else None


def paired_tasks(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> set[str]:
    """Tasks BOTH sides ran — the only tasks on which two versions are comparable."""
    return ({t for t in map(_task_of, a) if t} & {t for t in map(_task_of, b) if t})


def _on_tasks(runs: list[dict[str, Any]], tasks: set[str]) -> list[dict[str, Any]]:
    return [r for r in runs if _task_of(r) in tasks]


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
            min_runs: int = MIN_RUNS, root: Optional[Path] = None,
            only_tasks: Optional[set[str]] = None) -> dict[str, Any]:
    """Grade this kind's CURRENT profile version against the previous one, on the tasks
    BOTH versions ran. `only_tasks` narrows that further to a declared fixed set
    (`evals/tasks.yaml`), so the A/B is over known work rather than whatever happened
    to be built."""
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

    if only_tasks is not None:
        cur_runs, prev_runs = _on_tasks(cur_runs, only_tasks), _on_tasks(prev_runs, only_tasks)
    shared = paired_tasks(cur_runs, prev_runs)
    # Judge on the shared tasks only. Without them the two versions did different work
    # and any delta is a difference in the WORK, not in the prompt.
    cur_cmp = _on_tasks(cur_runs, shared) if shared else cur_runs
    prev_cmp = _on_tasks(prev_runs, shared) if shared else prev_runs

    out: dict[str, Any] = {
        "kind": kind,
        "current_digest": current_digest,
        "previous_digest": prev_digest,
        "current": metrics(cur_cmp),
        "previous": metrics(prev_cmp),
        "comparison": "matched-pairs" if shared else "unpaired",
        "paired_tasks": sorted(shared),
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
    # An EMPTY side comes first: "they share no task" is technically true when one
    # version has no runs at all, but it hides the useful fact, which is that the version
    # has not been exercised yet. Naming the empty side tells the operator what to do.
    if not cur_runs or not prev_runs:
        empty = "current" if not cur_runs else "previous"
        out.update(verdict="insufficient-data", reason=(
            f"the {empty} version has no measured runs"
            + (" on the declared eval set" if only_tasks else "")
            + f" (current {len(cur_runs)}, previous {len(prev_runs)})"))
        return out

    # ORDER MATTERS. "They did different work" is a STRUCTURAL failure to compare and
    # outranks "the sample is small": reporting `insufficient-data` for disjoint tasks
    # would invite someone to fix it by collecting more unpaired runs, which can never
    # make the two versions comparable.
    if not shared:
        # Report what the numbers say — a regression is worth seeing — but certify
        # nothing: the two versions did not run the same work.
        note = ("; the deltas shown are CONFOUNDED by that difference"
                + (f" and point to a regression in {', '.join(regressions)}"
                   if regressions else ""))
        out.update(verdict="unpaired", reason=(
            "the two versions share no task, so they are not comparable "
            f"(current ran {sorted({t for t in map(_task_of, cur_runs) if t})}, "
            f"previous ran {sorted({t for t in map(_task_of, prev_runs) if t})})" + note))
        return out
    if len(cur_cmp) < min_runs or len(prev_cmp) < min_runs:
        out.update(verdict="insufficient-data", reason=(
            f"need >={min_runs} runs per version to judge on the {len(shared)} shared "
            f"task(s) (current {len(cur_cmp)}, previous {len(prev_cmp)})"))
        return out
    if regressions:
        out.update(verdict="regressed", reason=(
            f"worse than the previous version on {len(shared)} shared task(s): "
            + ", ".join(regressions)))
    else:
        out.update(verdict="improved" if improvements else "ok",
                   reason=((f"better on {len(shared)} shared task(s): "
                            + ", ".join(improvements)) if improvements
                           else f"within tolerance over {len(shared)} shared task(s)"))
    return out


def check(kinds: Optional[list[str]] = None, *, strict: bool = False,
          runs: Optional[list[dict[str, Any]]] = None,
          root: Optional[Path] = None,
          only_tasks: Optional[set[str]] = None,
          use_task_set: bool = True) -> tuple[bool, list[dict[str, Any]]]:
    """(ok, results). A regression always fails. A broken profile always fails — it
    silently stops attributing runs. "insufficient-data"/"no-data"/"unpaired" pass
    unless strict, because a gate that cannot measure must not pretend to have
    measured.

    By default the A/B is restricted to the declared eval set (`evals/tasks.yaml`);
    `use_task_set=False` compares on any task both versions ran."""
    from area.profile import all_profiles, broken_profiles

    broken = broken_profiles(root=root)
    names = kinds or sorted(all_profiles(root=root))
    # Only impose the repo's declared set on the REAL installation. `root` here names
    # the profiles directory, not a repo root, so it cannot locate evals/tasks.yaml;
    # and an explicit root means an alternate/synthetic install whose runs have nothing
    # to do with this repo's eval tasks. Such a caller passes `only_tasks` itself.
    if only_tasks is None and use_task_set and root is None:
        only_tasks = load_task_set()
    results = [compare(k, runs=runs, root=root, only_tasks=only_tasks) for k in names]
    for name, why in broken.items():
        results.append({"kind": name, "verdict": "broken", "reason": why})
    bad = {"regressed", "broken"}
    if strict:
        bad |= {"insufficient-data", "no-data", "no-profile", "unpaired"}
    return (not any(r["verdict"] in bad for r in results)), results


_ICON = {"ok": "✅", "improved": "🎉", "regressed": "❌", "broken": "💥",
         "insufficient-data": "…", "no-data": "–", "new-profile": "🆕",
         "no-profile": "?", "unpaired": "⚖"}


def report_text(results: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for r in sorted(results, key=lambda r: (r["verdict"] != "regressed", r["kind"])):
        lines.append(f"  {_ICON.get(r['verdict'], ' ')} {r['kind']:24s} "
                     f"{r['verdict']:18s} {r.get('reason', '')}")
        if r.get("paired_tasks"):
            lines.append(f"        on task(s): {', '.join(r['paired_tasks'])}")
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


# ---- the evidence-gated experience log (Harness2's one habit worth taking) ----

# Verdicts that mean something was actually measured. Anything else — no data, a new
# profile, too small a sample, or two versions that ran different work — is not evidence.
DECISIVE = ("improved", "regressed", "ok")


def record_experience(kind: str, note: str, *,
                      runs: Optional[list[dict[str, Any]]] = None,
                      root: Optional[Path] = None,
                      when: Optional[str] = None) -> tuple[bool, str]:
    """Append an evidence-stamped entry to `profiles/<kind>.yaml`, or REFUSE and say why.

    This is the one idea taken from Harness2's improvement library (arXiv:2610.14224):
    an entry is written only when the evidence supports one — "if the evidence is
    insufficient, reflection adds no entry". The difference is what counts as evidence:
    Harness2 has no ground-truth verifier and leans on model judgement over behavioural
    contrast, while here it is `compare()`'s own verdict over matched tasks. So the gate
    is `verdict in DECISIVE`, and `unpaired` / `insufficient-data` / `no-data` /
    `new-profile` all refuse.

    The entry carries the evidence beside the claim — digest, verdict, the tasks it was
    measured on, the sample sizes and the deltas — so a later reader can tell a measured
    lesson from an asserted one. That is the whole point: a notes field nothing verifies
    is how `description` and `notes` came to be prose nobody reads.

    Appends as TEXT rather than re-dumping the YAML, because these files are mostly
    comments and `safe_dump` would delete every one of them.
    """
    import datetime

    res = compare(kind, runs=runs, root=root)
    verdict = res.get("verdict")
    if verdict not in DECISIVE:
        return False, (f"refused: `area evals` says {verdict} for '{kind}' "
                       f"({res.get('reason')}) — there is nothing measured to record")
    note = " ".join(note.split()).strip()
    if not note:
        return False, "refused: the note is empty"

    from area.profile import PROFILES_DIR

    f = (Path(root) if root else PROFILES_DIR) / f"{kind}.yaml"
    if not f.is_file():
        return False, f"refused: no {f}"

    entry = {
        "when": when or datetime.date.today().isoformat(),
        "digest": res.get("current_digest"),
        "verdict": verdict,
        "tasks": list(res.get("paired_tasks") or []),
        "runs": {"current": res["current"].get("n"), "previous": res["previous"].get("n")},
        "deltas": {k: v for k, v in (res.get("deltas") or {}).items() if v is not None},
        "note": note,
    }
    block = yaml.safe_dump([entry], sort_keys=True, allow_unicode=True,
                           default_flow_style=False).rstrip("\n")
    text = f.read_text()
    if re.search(r"^experience:\s*$", text, re.M):
        text = text.rstrip("\n") + "\n" + block + "\n"
    else:
        text = (text.rstrip("\n")
                + "\n\n# Evidence-stamped lessons, appended ONLY by `area evals --record`,\n"
                  "# which refuses unless `area evals` reached a decisive verdict.\n"
                  "experience:\n" + block + "\n")
    f.write_text(text)
    return True, f"recorded against {entry['digest']} ({verdict} on {entry['tasks']})"


def experience_index(root: Optional[Path] = None) -> list[dict[str, Any]]:
    """Every recorded lesson across all kinds, newest first — the lookup half of the
    library. Harness2 keeps an index so a later session can find the relevant entry;
    without one a log is just an append-only file nobody reads."""
    from area.profile import all_profiles

    out: list[dict[str, Any]] = []
    for kind, prof in sorted(all_profiles(root=root).items()):
        for e in prof.experience:
            out.append({"kind": kind, **e})
    return sorted(out, key=lambda e: str(e.get("when") or ""), reverse=True)


def experience_text(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return ("[area] evals: no recorded experience yet. `area evals <kind> --record "
                "\"<lesson>\"` writes one, and refuses unless there is a measured verdict "
                "to attach it to.")
    lines = [f"[area] evals: {len(entries)} recorded lesson(s), newest first"]
    for e in entries:
        tasks = ", ".join(e.get("tasks") or []) or "—"
        lines.append(f"  {e.get('when')}  {e.get('kind')}  [{e.get('verdict')}] on {tasks}")
        lines.append(f"      {e.get('note')}")
        if e.get("deltas"):
            lines.append(f"      evidence: {e['deltas']}  runs={e.get('runs')}")
    return "\n".join(lines)
