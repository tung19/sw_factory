"""area.obs.summary — determinism + cost aggregation (PR3). `outer_iters` is the
attempt a convergence loop went green on (1 = first-try, >1 = retried); runs with
a null outer_iters (run_once, e.g. authoring) are excluded from determinism rates.
summary() takes an explicit runs list here so no file I/O is needed."""
import area.obs as O

RUNS = [
    {"label": "build", "cost_usd": 5.0, "duration_s": 900, "outer_iters": 1, "passed": True},
    {"label": "build", "cost_usd": 3.0, "duration_s": 600, "outer_iters": 2, "passed": True},
    {"label": "chaos", "cost_usd": 3.0, "duration_s": 500, "outer_iters": 3, "passed": True},
    {"label": "author", "cost_usd": 2.0, "duration_s": 300, "outer_iters": None, "passed": True},
    {"label": "e2e", "cost_usd": 1.0, "duration_s": 100, "outer_iters": 3, "passed": False},
]


def test_overall_determinism_and_cost():
    s = O.summary(RUNS)
    assert s["runs"] == 5
    assert s["total_cost_usd"] == 14.0
    assert s["avg_cost_usd"] == round(14.0 / 5, 4)        # all 5 have a cost
    assert s["convergence_runs"] == 4                     # author (null iters) excluded
    assert s["first_try_rate"] == 0.25                    # only build#1 (iters==1 & passed)
    assert s["retry_rate"] == 0.75                        # build#2, chaos, e2e had iters>1
    assert s["avg_iters"] == round((1 + 2 + 3 + 3) / 4, 2)  # 2.25


def test_per_label_breakdown():
    by = O.summary(RUNS)["by_label"]
    assert by["build"]["n"] == 2 and by["build"]["ok"] == 2
    assert by["build"]["avg_cost"] == 4.0
    assert by["build"]["conv_n"] == 2 and by["build"]["first_try"] == 1
    assert by["build"]["avg_iters"] == 1.5
    # e2e failed at the cap: counts as retried, not first-try
    assert by["e2e"]["ok"] == 0 and by["e2e"]["first_try"] == 0 and by["e2e"]["retried"] == 1
    # author has a null outer_iters → no convergence stats
    assert by["author"]["conv_n"] == 0 and by["author"]["avg_iters"] is None


def test_empty_is_safe():
    s = O.summary([])
    assert s["runs"] == 0
    assert s["first_try_rate"] is None and s["avg_iters"] is None
    assert s["avg_cost_usd"] is None and s["by_label"] == {}


def test_backward_compatible_keys_present():
    s = O.summary(RUNS)
    # keys the CLI `area obs` relies on must still exist
    for k in ("runs", "total_cost_usd", "total_time_s", "by_label"):
        assert k in s
    for k in ("n", "ok", "cost", "time"):
        assert k in s["by_label"]["build"]
