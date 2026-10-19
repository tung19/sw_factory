"""Optional Langfuse tracing: a trace per pipeline run, a span per agent run.
Validated with a fake sink so no langfuse install / network is needed, plus the
no-op path (the keyless default) must never raise."""
import pytest

import area.obs as O
import area.trace as T


class FakeTrace:
    def __init__(self, **kw):
        self.kw = kw
        self.spans = []
        self.updated = None

    def span(self, **kw):
        self.spans.append(kw)

    def update(self, **kw):
        self.updated = kw

    def get_trace_url(self):
        return "http://langfuse.local/trace/abc"


class FakeSink:
    def __init__(self):
        self.traces = []
        self.flushed = 0

    def trace(self, **kw):
        t = FakeTrace(**kw)
        self.traces.append(t)
        return t

    def flush(self):
        self.flushed += 1


@pytest.fixture(autouse=True)
def _reset():
    T.set_sink(None)
    yield
    T.set_sink(None)


def test_noop_when_disabled():
    T.set_sink(None)
    assert not T.enabled()
    # none of these may raise with no sink
    T.start_pipeline("app", "run", inputs={"x": 1})
    T.log_span("spec", duration=1.0, cost=0.3, passed=True)
    T.end_pipeline(passed=True)


def test_trace_and_spans_recorded():
    fake = FakeSink()
    T.set_sink(fake)
    assert T.enabled()
    T.start_pipeline("myapp", "run", inputs={"requirement": "x"})
    T.log_span("spec", duration=2.0, cost=0.3, passed=True, backend="ACPAgent")
    T.log_span("build:plain:tdd", duration=5.0, cost=1.2, passed=True)
    T.end_pipeline(passed=True, output={"name": "myapp"})

    assert len(fake.traces) == 1
    t = fake.traces[0]
    assert t.kw["name"] == "run:myapp"
    assert [s["name"] for s in t.spans] == ["spec", "build:plain:tdd"]
    assert t.spans[0]["metadata"]["cost_usd"] == 0.3
    assert t.spans[0]["metadata"]["backend"] == "ACPAgent"
    assert t.updated is not None and fake.flushed == 1


def test_failed_span_marked_error():
    fake = FakeSink()
    T.set_sink(fake)
    T.start_pipeline("app", "run")
    T.log_span("build", duration=1.0, passed=False)
    assert fake.traces[0].spans[0]["level"] == "ERROR"


def test_span_without_active_trace_is_noop():
    fake = FakeSink()
    T.set_sink(fake)
    # no start_pipeline -> no current trace
    T.log_span("orphan", duration=1.0)
    assert fake.traces == []


def test_obs_log_run_emits_span(monkeypatch, tmp_path):
    fake = FakeSink()
    T.set_sink(fake)
    monkeypatch.setattr(O, "RUNS", tmp_path / "runs.jsonl")  # isolate the jsonl
    T.start_pipeline("app", "run")
    O.log_run("spec", duration=1.0, cost=0.5, passed=True, backend="ACPAgent")
    T.end_pipeline(passed=True)
    names = [s["name"] for s in fake.traces[0].spans]
    assert "spec" in names
