"""A partial total must not be printed as the total.

`build_cost()` drops rows with no `cost_usd` and sums the rest. Only the ACP backend
reports a cost: `ask_cli` (the spec reviewer, the product reviewer) reports none, and so
did the older `_Agent` runs — in the live ledger **94 of 204 rows carry no price at
all**. So the gate could price three runs out of eight and print `$0.42 spent / $5.00
cap — ok`, which reads as "this build cost $0.42".

The all-unpriced case was already handled loudly (a previous remediation). This is the
PARTIAL case, which took the normal path and said nothing.
"""
from area.verify import cost as C


def _run(ts, *, name="a", cost=None, backend="ACPAgent"):
    r = {"ts": ts, "label": "build", "name": name, "duration_s": 1.0, "backend": backend}
    if cost is not None:
        r["cost_usd"] = cost
    return r


def test_coverage_counts_priced_against_total_in_scope():
    runs = [_run(1, cost=0.5), _run(2), _run(3, cost=0.25),
            _run(4, name="other", cost=9.0), _run(5)]
    assert C.cost_coverage(name="a", runs=runs) == (2, 4)
    assert C.cost_coverage(name="other", runs=runs) == (1, 1)
    assert C.cost_coverage(runs=runs) == (3, 5)


def test_coverage_honours_the_since_window():
    runs = [_run(1, cost=1.0), _run(10), _run(20, cost=2.0)]
    assert C.cost_coverage(since=10, runs=runs) == (1, 2)


def _gate(tmp_path, monkeypatch, runs, *, cap="max_usd: 5.0\n", strict=False):
    (tmp_path / "apps" / "a").mkdir(parents=True)
    d = tmp_path / "specs" / "a"
    d.mkdir(parents=True)
    (d / "cost.yaml").write_text(cap)
    monkeypatch.setattr(C, "load_runs", lambda: runs)
    return C.cost_verify("a", strict=strict, root=tmp_path)


def test_a_partial_total_is_never_printed_as_ok(tmp_path, monkeypatch, capsys):
    """Three priced runs, five unpriced, under the cap on what could be priced."""
    runs = [_run(1, cost=0.1), _run(2, cost=0.2), _run(3, cost=0.1)] + [
        _run(i, backend="claude-cli") for i in range(4, 9)]
    assert _gate(tmp_path, monkeypatch, runs) is True        # advisory by default
    out = capsys.readouterr().out
    assert "priced 3 of 8" in out
    assert "real total is ≥" in out
    assert "UNVERIFIED" in out


def test_strict_turns_the_unknown_remainder_into_a_failure(tmp_path, monkeypatch, capsys):
    runs = [_run(1, cost=0.1)] + [_run(2, backend="claude-cli")]
    assert _gate(tmp_path, monkeypatch, runs, strict=True) is False
    assert "FAIL" in capsys.readouterr().out


def test_full_coverage_still_reads_as_a_plain_ok(tmp_path, monkeypatch, capsys):
    """The warning must not fire when every run in scope was priced — otherwise it is
    noise and gets ignored, which is how a real warning stops working."""
    runs = [_run(1, cost=0.1), _run(2, cost=0.2)]
    assert _gate(tmp_path, monkeypatch, runs) is True
    out = capsys.readouterr().out
    assert "ok" in out
    assert "UNVERIFIED" not in out and "priced" not in out


def test_going_over_the_cap_still_blocks_regardless_of_coverage(tmp_path, monkeypatch):
    """Partial pricing can only UNDERSTATE spend, so a measured breach is still a
    breach — the coverage warning must not soften it."""
    runs = [_run(1, cost=9.0), _run(2, backend="claude-cli")]
    assert _gate(tmp_path, monkeypatch, runs) is False
