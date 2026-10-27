"""area.evals — grade a change to the FACTORY (group 4 / item 13).

AREA's rule is "never let the same reasoning write AND grade". Applied to AREA itself:
when a prompt/skill/knob changes, something independent has to measure whether it
helped. These tests pin the judging rules on synthetic run logs — no agent, no money.
"""
import yaml

from area import evals as E
from area import profile as P


def _profile(root, kind="k", **over):
    raw = {"kind": kind, "labels": over.pop("labels", [kind]), "prompt_sources": [],
           "skills": "none", "defaults": {}}
    raw.update(over)
    (root / f"{kind}.yaml").write_text(yaml.safe_dump(raw))


# The default task set every version is measured on. Two versions are only comparable
# on tasks they BOTH ran, so a fixture that leaves `name` unset is a version that can
# be compared with nothing — see test_disjoint_tasks_certify_nothing.
TASKS = ("t1", "t2", "t3", "t4", "t5")


def _runs(digest, n, *, kind="k", iters=1, passed=True, cost=1.0, ts0=0.0,
          tasks=TASKS):
    return [{"ts": ts0 + i, "label": kind, "profile": kind,
             "name": tasks[i % len(tasks)] if tasks else None,
             "profile_digest": digest, "outer_iters": iters, "passed": passed,
             "cost_usd": cost, "duration_s": 10.0} for i in range(n)]


# ---- metrics ------------------------------------------------------------------
def test_metrics_are_none_not_zero_when_unmeasurable():
    """A missing metric must not read as a measured zero — that would look like a
    catastrophic regression."""
    m = E.metrics([{"label": "k"}])
    assert m["n"] == 1
    assert m["pass_rate"] is None and m["first_try_rate"] is None
    assert m["avg_iters"] is None and m["avg_cost_usd"] is None


def test_metrics_compute_the_real_rates():
    runs = (_runs("d", 3, iters=1, passed=True, cost=1.0)
            + _runs("d", 1, iters=3, passed=True, cost=5.0))
    m = E.metrics(runs)
    assert m["n"] == 4 and m["first_try_rate"] == 0.75
    assert m["avg_iters"] == 1.5 and m["avg_cost_usd"] == 2.0
    assert m["pass_rate"] == 1.0


# ---- verdicts -----------------------------------------------------------------
def _compare(tmp_path, runs, **kw):
    _profile(tmp_path)
    return E.compare("k", runs=runs, root=tmp_path, **kw)


def test_no_data_names_legacy_runs_instead_of_claiming_nothing_ran(tmp_path):
    """Regression guard: the first version reported "no runs recorded" for every kind
    while 110 real runs sat in the log — true that none were attributable, false that
    none existed."""
    legacy = [{"ts": 1, "label": "k", "duration_s": 1.0}] * 7   # no profile_digest
    r = _compare(tmp_path, legacy)
    assert r["verdict"] == "no-data"
    assert r["unattributed_runs"] == 7 and "predate profiles" in r["reason"]

    r2 = _compare(tmp_path, [])
    assert r2["verdict"] == "no-data" and "never run" in r2["reason"]


def test_new_profile_when_there_is_only_one_measured_version(tmp_path):
    _profile(tmp_path)
    cur = P.load_profile("k", root=tmp_path).digest
    r = E.compare("k", runs=_runs(cur, 8), root=tmp_path)
    assert r["verdict"] == "new-profile" and r["previous_digest"] is None


def test_insufficient_data_when_either_side_is_too_small(tmp_path):
    """The sample that counts is the PAIRED one. The previous version has 9 runs, but
    only 4 of them are on the 2 tasks the 2-run current version also ran — judging on
    9 would be comparing different work."""
    _profile(tmp_path)
    cur = P.load_profile("k", root=tmp_path).digest
    runs = _runs("old", 9, ts0=0) + _runs(cur, 2, ts0=100)
    r = E.compare("k", runs=runs, root=tmp_path)
    assert r["verdict"] == "insufficient-data"
    assert r["paired_tasks"] == ["t1", "t2"]
    assert "current 2" in r["reason"] and "previous 4" in r["reason"]


def test_ok_when_within_tolerance(tmp_path):
    _profile(tmp_path)
    cur = P.load_profile("k", root=tmp_path).digest
    runs = _runs("old", 6, cost=1.0, ts0=0) + _runs(cur, 6, cost=1.05, ts0=100)
    r = E.compare("k", runs=runs, root=tmp_path)
    assert r["verdict"] == "ok", r


def test_regression_on_first_try_rate(tmp_path):
    _profile(tmp_path)
    cur = P.load_profile("k", root=tmp_path).digest
    old = _runs("old", 10, iters=1, ts0=0)                      # first-try 1.00
    new = _runs(cur, 8, iters=1, ts0=100) + _runs(cur, 2, iters=2, ts0=200)  # 0.80
    r = E.compare("k", runs=old + new, root=tmp_path)
    assert r["verdict"] == "regressed" and "first_try_rate" in r["reason"]
    assert r["deltas"]["first_try_rate"] < 0


def test_regression_on_cost_is_relative_not_absolute(tmp_path):
    """A cheap stage going 0.01 -> 0.02 is a 100% rise and should be caught; an
    absolute threshold would miss it."""
    _profile(tmp_path)
    cur = P.load_profile("k", root=tmp_path).digest
    runs = _runs("old", 6, cost=0.01, ts0=0) + _runs(cur, 6, cost=0.02, ts0=100)
    r = E.compare("k", runs=runs, root=tmp_path)
    assert r["verdict"] == "regressed" and "avg_cost_usd" in r["reason"]
    assert r["deltas"]["avg_cost_usd"] == 1.0


def test_improvement_is_reported_not_just_tolerated(tmp_path):
    _profile(tmp_path)
    cur = P.load_profile("k", root=tmp_path).digest
    runs = _runs("old", 6, iters=2, ts0=0) + _runs(cur, 6, iters=1, ts0=100)
    r = E.compare("k", runs=runs, root=tmp_path)
    assert r["verdict"] == "improved" and "first_try_rate" in r["reason"]


def test_missing_profile_is_its_own_verdict(tmp_path):
    assert E.compare("ghost", runs=[], root=tmp_path)["verdict"] == "no-profile"


# ---- the gate -----------------------------------------------------------------
def test_check_fails_on_regression_and_on_a_broken_profile(tmp_path):
    _profile(tmp_path)
    cur = P.load_profile("k", root=tmp_path).digest
    runs = _runs("old", 10, iters=1, ts0=0) + _runs(cur, 10, iters=2, ts0=100)
    ok, results = E.check(["k"], runs=runs, root=tmp_path)
    assert ok is False and results[0]["verdict"] == "regressed"

    (tmp_path / "broken.yaml").write_text("kind: broken\nx: >-\n  a\nnope\n")
    ok2, res2 = E.check(runs=[], root=tmp_path)
    assert ok2 is False
    assert any(r["verdict"] == "broken" for r in res2)


def test_check_passes_when_it_cannot_measure_but_strict_fails(tmp_path):
    """A gate that cannot measure must not pretend it did — advisory by default,
    and `--strict` is how you say "I need certainty"."""
    _profile(tmp_path)
    ok, res = E.check(["k"], runs=[], root=tmp_path)
    assert ok is True and res[0]["verdict"] == "no-data"
    ok_strict, _ = E.check(["k"], runs=[], root=tmp_path, strict=True)
    assert ok_strict is False


def test_report_text_is_readable_and_shows_the_deltas(tmp_path):
    _profile(tmp_path)
    cur = P.load_profile("k", root=tmp_path).digest
    runs = _runs("old", 6, iters=1, ts0=0) + _runs(cur, 6, iters=2, ts0=100)
    _, results = E.check(["k"], runs=runs, root=tmp_path)
    txt = E.report_text(results)
    assert "regressed" in txt and "first_try_rate" in txt and "avg_iters" in txt


def test_check_covers_every_shipped_profile_by_default():
    """So adding a profile cannot quietly escape the gate."""
    ok, results = E.check()
    assert {r["kind"] for r in results} >= set(P.all_profiles())
    assert ok is True  # no attributed history yet -> advisory, not a failure


def test_evals_is_not_an_app_gate():
    """Category distinction, pinned so nobody "helpfully" adds it to `_GATE_ORDER`:
    the gate set decides whether an APP may ship, while evals decides whether a
    change to the FACTORY may be promoted. Folding it in would block an app build
    because a prompt regressed, and would run it after every build."""
    import area.cli as C

    assert "evals" not in C._GATE_ORDER
    assert "evals" in C._HANDLERS          # a command of its own


# ---- matched pairs (the Harness2 "probe" rule) ---------------------------------

def test_disjoint_tasks_certify_nothing(tmp_path):
    """Two versions that ran different work are not comparable: a prompt that looks
    better may simply have drawn easier tasks. The old aggregate comparison would have
    called this `ok`."""
    _profile(tmp_path)
    cur = P.load_profile("k", root=tmp_path).digest
    runs = (_runs(cur, 6, tasks=("a1", "a2")) + _runs("old", 6, tasks=("b1", "b2")))
    r = E.compare("k", runs=runs, root=tmp_path)
    assert r["verdict"] == "unpaired"
    assert r["comparison"] == "unpaired" and r["paired_tasks"] == []
    assert "share no task" in r["reason"] and "CONFOUNDED" in r["reason"]


def test_a_regression_is_still_surfaced_when_unpaired(tmp_path):
    """Certify nothing, but do not hide it: an unpairable regression is still named,
    because it is worth seeing even when it cannot be attributed."""
    _profile(tmp_path)
    cur = P.load_profile("k", root=tmp_path).digest
    runs = (_runs(cur, 6, iters=4, tasks=("a1",)) + _runs("old", 6, iters=1, tasks=("b1",)))
    r = E.compare("k", runs=runs, root=tmp_path)
    assert r["verdict"] == "unpaired"
    assert "regression" in r["reason"] and "avg_iters" in r["reason"]


def test_only_the_shared_tasks_are_judged(tmp_path):
    """The new version also ran an extra easy task; it must not count. On the shared
    task it is WORSE, and that is the verdict."""
    _profile(tmp_path)
    cur = P.load_profile("k", root=tmp_path).digest
    runs = (_runs(cur, 5, iters=4, tasks=("shared",))        # shared: 4 iters
            + _runs(cur, 5, iters=1, tasks=("easy-extra",))  # must be ignored
            + _runs("old", 5, iters=1, tasks=("shared",)))     # shared: 1 iter
    r = E.compare("k", runs=runs, root=tmp_path)
    assert r["comparison"] == "matched-pairs" and r["paired_tasks"] == ["shared"]
    assert r["current"]["avg_iters"] == 4.0 and r["previous"]["avg_iters"] == 1.0
    assert r["verdict"] == "regressed"


def test_only_tasks_narrows_to_a_declared_fixed_set(tmp_path):
    """`only_tasks` is how a declared eval set (evals/tasks.yaml) pins the A/B to known
    work: the off-set task is dropped even though both versions ran it."""
    _profile(tmp_path)
    cur = P.load_profile("k", root=tmp_path).digest
    runs = (_runs(cur, 5, iters=1, tasks=("declared",)) + _runs(cur, 5, iters=9, tasks=("adhoc",))
            + _runs("old", 5, iters=1, tasks=("declared",)) + _runs("old", 5, iters=1, tasks=("adhoc",)))
    wide = E.compare("k", runs=runs, root=tmp_path)
    narrow = E.compare("k", runs=runs, root=tmp_path, only_tasks={"declared"})
    assert sorted(wide["paired_tasks"]) == ["adhoc", "declared"]
    assert narrow["paired_tasks"] == ["declared"]
    assert wide["verdict"] == "regressed"   # dragged down by the ad-hoc task
    assert narrow["verdict"] == "ok"        # on the declared set they match


def test_insufficient_data_counts_the_PAIRED_runs(tmp_path):
    """Plenty of runs each, but only one shared task — the sample that matters is the
    paired one, and saying so beats judging on 20 unpaired runs."""
    _profile(tmp_path)
    cur = P.load_profile("k", root=tmp_path).digest
    runs = (_runs(cur, 10, tasks=("s", "n1", "n2", "n3", "n4", "n5", "n6", "n7", "n8", "n9"))
            + _runs("old", 10, tasks=("s", "o1", "o2", "o3", "o4", "o5", "o6", "o7", "o8", "o9")))
    r = E.compare("k", runs=runs, root=tmp_path)
    assert r["verdict"] == "insufficient-data"
    assert "shared task(s)" in r["reason"]


def test_the_declared_eval_set_is_real_and_names_apps_with_locked_oracles(tmp_path):
    """`evals/tasks.yaml` is the fixed A/B set. Its names are the PAIRING KEY — the app
    name `obs.set_app()` stamps — so a typo silently makes every comparison unpaired."""
    declared = E.load_task_set()
    assert declared, "the repo must declare an eval set"
    assert declared == {"taskboard", "invoice_mgr", "fb_incept"}

    # absent file -> None, i.e. "compare on any shared task", not "compare on nothing"
    assert E.load_task_set(tmp_path) is None


def test_check_does_not_impose_the_repo_eval_set_on_a_synthetic_root(tmp_path):
    """Regression guard: `check()` first read evals/tasks.yaml unconditionally, so a
    caller with its own profiles root had every run filtered out and every verdict came
    back `unpaired`."""
    _profile(tmp_path)
    cur = P.load_profile("k", root=tmp_path).digest
    runs = _runs("old", 6, iters=1, ts0=0) + _runs(cur, 6, iters=2, ts0=100)
    ok, results = E.check(["k"], runs=runs, root=tmp_path)
    assert results[0]["verdict"] == "regressed" and ok is False
