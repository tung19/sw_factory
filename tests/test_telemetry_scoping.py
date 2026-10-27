"""Round-2 audit remediation — telemetry scoping.
#5 cost gate is now app-scoped (obs rows carry the app name; build_cost filters by
it; a committed blocking cap that can't be measured on a keyless backend warns
loudly instead of silently passing).
#9 evidence.read_trail filters to ONE trace_id (default: the current run) so an
iterated app no longer concatenates every historical build's events."""
import area.evidence as E
import area.obs as O
import area.verify.cost as C


# ---- #5a: obs stamps the app name; build_cost filters by it --------------------

def test_log_run_stamps_current_app(tmp_path, monkeypatch):
    monkeypatch.setattr(O, "RUNS", tmp_path / ".area" / "runs.jsonl")
    monkeypatch.setattr(O, "_current_app", None)
    O.set_app("appA")
    O.log_run("build:plain", duration=1.0, cost=0.5)
    O.set_app("appB")
    O.log_run("build:plain", duration=1.0, cost=9.0)
    rows = O.load_runs()
    by = {r["name"]: r["cost_usd"] for r in rows}
    assert by == {"appA": 0.5, "appB": 9.0}


def test_build_cost_filters_by_app():
    rows = [
        {"ts": 100.0, "cost_usd": 1.0, "name": "appA"},
        {"ts": 101.0, "cost_usd": 8.0, "name": "appB"},   # concurrent other app
        {"ts": 102.0, "cost_usd": 2.0, "name": "appA"},
    ]
    # since-window: only appA's spend, NOT appB's concurrent $8
    assert C.build_cost(name="appA", since=0.0, runs=rows) == 3.0
    assert C.build_cost(name="appB", since=0.0, runs=rows) == 8.0
    # no name → unscoped (back-compat)
    assert C.build_cost(since=0.0, runs=rows) == 11.0


def test_cost_verify_scopes_to_app(tmp_path, monkeypatch):
    spec = tmp_path / "specs" / "appA"; spec.mkdir(parents=True)
    (spec / "cost.yaml").write_text("max_usd: 5\n")
    rows = [
        {"ts": 100.0, "cost_usd": 2.0, "name": "appA"},
        {"ts": 100.5, "cost_usd": 50.0, "name": "appB"},  # expensive neighbour
    ]
    monkeypatch.setattr(C, "load_runs", lambda: rows)
    # appA spent $2 ≤ $5 — must PASS despite appB's concurrent $50 in the same log
    assert C.cost_verify("appA", since=0.0, root=tmp_path) is True


# ---- #5b: blocking cap that can't be measured (keyless) warns, doesn't fail ----

def test_cost_verify_keyless_blocking_warns(tmp_path, monkeypatch, capsys):
    spec = tmp_path / "specs" / "appA"; spec.mkdir(parents=True)
    (spec / "cost.yaml").write_text("max_usd: 5\n")       # committed → blocking
    # runs happened for appA but the backend reported no cost
    monkeypatch.setattr(C, "load_runs",
                        lambda: [{"ts": 100.0, "cost_usd": None, "name": "appA"}])
    ok = C.cost_verify("appA", since=0.0, root=tmp_path)
    out = capsys.readouterr().out
    assert ok is True                       # can't enforce what it can't measure
    assert "cannot enforce" in out          # but it says so LOUDLY


def test_cost_verify_no_runs_is_quiet_skip(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(C, "load_runs", lambda: [])
    assert C.cost_verify("appA", since=0.0, root=tmp_path) is True
    assert "skipping" in capsys.readouterr().out


# ---- #9: evidence.read_trail filters to one trace ------------------------------

def _write_trail(tmp_path, monkeypatch, lines):
    sd = tmp_path / "specs" / "app"
    sd.mkdir(parents=True)
    monkeypatch.setattr(E, "_spec_dir", lambda name: sd)
    import json
    (sd / "aidlc_trace.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))
    return sd


def test_read_trail_defaults_to_current_trace(tmp_path, monkeypatch):
    _write_trail(tmp_path, monkeypatch, [
        {"ts": 1.0, "trace": "t-old", "event": "build.green"},
        {"ts": 2.0, "trace": "t-old", "event": "deploy.done"},
        {"ts": 3.0, "trace": "t-new", "event": "intake.start"},
        {"ts": 4.0, "trace": "t-new", "event": "build.green"},
    ])
    # default = current (latest) trace → only t-new's 2 events, not all 4
    events = [r["event"] for r in E.read_trail("app")]
    assert events == ["intake.start", "build.green"]


def test_read_trail_explicit_trace(tmp_path, monkeypatch):
    _write_trail(tmp_path, monkeypatch, [
        {"ts": 1.0, "trace": "t-old", "event": "a"},
        {"ts": 3.0, "trace": "t-new", "event": "b"},
    ])
    assert [r["event"] for r in E.read_trail("app", trace="t-old")] == ["a"]


def test_read_trail_stable_order_on_tie(tmp_path, monkeypatch):
    # equal ts must keep file (append) order, not sort ambiguously
    _write_trail(tmp_path, monkeypatch, [
        {"ts": 5.0, "trace": "t", "event": "first"},
        {"ts": 5.0, "trace": "t", "event": "second"},
        {"ts": 5.0, "trace": "t", "event": "third"},
    ])
    assert [r["event"] for r in E.read_trail("app")] == ["first", "second", "third"]
