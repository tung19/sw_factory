"""The UI must be something the build loop CONVERGES on, not just something we can
measure afterwards.

Tung's original complaint was that a clone's UI is "always missing". Part A gave the
builder the reference's real CSS/tokens/markup in `.area-ui/`, and part C could score
the result — but the loop's oracle was still `npm install && build && test`, so it
converged on BEHAVIOUR and the builder never received one signal about the look. Worse,
gates are opt-in, so for a plain `area clone` the visual gate never ran at all: AREA
captured the reference UI, vendored it, built a gate to score it, and then by default
scored nothing.

Two fixes, both tested here: the gate is auto-selected for a clone with captured UI,
and a UI term is added to the build loop's oracle.

Agent-free: the oracle's base verifier and `measure` are stubbed; one case runs the
REAL measurement over a tiny fixture.
"""
import argparse
import types

import yaml

import area.build.nextjs as B
import area.cli as C
from area.engine import VerifyResult
from area.verify import visual as V


def _ws(tmp_path, name="t", *, captured=True, tokens=None, rendered_html=None):
    app = tmp_path / "apps" / name
    (app / "app").mkdir(parents=True)
    ui = tmp_path / "specs" / name / "_ui"
    (ui / "rendered").mkdir(parents=True)
    man = {"captured": captured, "source_kind": "repo",
           "tokens": tokens or {"colors": ["#0ea5e9", "#111111"], "fonts": ["Inter"]},
           "rendered": ["rendered/index.html"]}
    (ui / "manifest.yaml").write_text(yaml.safe_dump(man))
    (ui / "rendered" / "index.html").write_text(
        rendered_html or '<div class="wrap"><header class="hd"><h1>Hi</h1></header></div>')
    return app


# ---- the floor, and why it is that number -----------------------------------
def test_the_loop_floor_sits_between_ignored_and_fidelity():
    """Pins the calibration rationale: an app that IGNORED the reference measured
    0.19-0.28, an identical one 1.00, and the gate's fidelity floor is 0.75. The loop
    floor only has to catch "did you use the vendored UI at all"."""
    assert 0.28 < V.UI_ORACLE_FLOOR < V.DEFAULT_MIN_SIMILARITY
    assert V.UI_ORACLE_FLOOR == 0.45


# ---- helpers ----------------------------------------------------------------
def test_has_reference_ui_only_for_a_successful_capture(tmp_path):
    _ws(tmp_path, "yes", captured=True)
    _ws(tmp_path, "no", captured=False)
    assert V.has_reference_ui("yes", root=tmp_path) is True
    assert V.has_reference_ui("no", root=tmp_path) is False
    assert V.has_reference_ui("absent", root=tmp_path) is False


def test_missing_tokens_names_what_to_add():
    ref = {"colors": ["#0ea5e9", "#111111"], "fonts": ["Inter", "sans-serif"]}
    clone = {"colors": ["#111111"], "fonts": ["sans-serif"]}
    assert V.missing_tokens(ref, clone) == {"colors": ["#0ea5e9"], "fonts": ["Inter"]}
    assert V.missing_tokens(ref, ref) == {}
    assert V.missing_tokens({}, clone) == {}


def test_measure_reports_missing_tokens(tmp_path):
    """The actionable half travels with the score, so callers need no path logic."""
    app = _ws(tmp_path)
    (app / "app" / "globals.css").write_text("body{color:#111111;font-family:Arial}")
    m = V.measure("t", root=tmp_path, pixel=False)
    assert m["missing_tokens"]["colors"] == ["#0ea5e9"]
    assert m["missing_tokens"]["fonts"] == ["Inter"]


# ---- the oracle -------------------------------------------------------------
def _oracle(app, *, ok=True, combined=0.9, monkeypatch=None, **extra):
    base = lambda: VerifyResult(ok=ok, feedback="tests said so")  # noqa: E731
    if monkeypatch is not None:
        monkeypatch.setattr(V, "measure", lambda n, **k: {
            "combined": combined, "scores": {"tokens": combined, "dom": combined},
            "skips": {}, "missing_tokens": extra.get("missing", {})})
    return B._with_ui_parity(base, app)


def test_a_failing_behaviour_test_is_returned_unchanged(tmp_path, monkeypatch):
    """Behaviour stays the hard requirement — and the look is not even measured, so a
    red suite cannot be masked by a pretty page."""
    app = _ws(tmp_path)
    called = []
    monkeypatch.setattr(V, "measure", lambda n, **k: called.append(1))
    res = _oracle(app, ok=False)()
    assert res.ok is False and res.feedback == "tests said so"
    assert called == [], "the UI must not be measured while behaviour is red"


def test_green_behaviour_and_a_good_score_passes(tmp_path, monkeypatch, capsys):
    app = _ws(tmp_path)
    assert _oracle(app, combined=0.82, monkeypatch=monkeypatch)().ok is True
    assert "ui-parity: 0.82" in capsys.readouterr().out


def test_green_behaviour_but_an_ignored_reference_keeps_the_loop_going(
        tmp_path, monkeypatch):
    """The fix for "the UI is always missing": the builder now gets told, and the loop
    does not stop just because the tests pass."""
    app = _ws(tmp_path)
    res = _oracle(app, combined=0.22, monkeypatch=monkeypatch,
                  missing={"colors": ["#0ea5e9"], "fonts": ["Inter"]})()
    assert res.ok is False
    fb = res.feedback
    assert "does NOT look like the reference" in fb and "0.22" in fb
    assert ".area-ui/tokens.json" in fb and ".area-ui/rendered/" in fb
    assert "#0ea5e9" in fb and "Inter" in fb          # actionable, not just a score
    assert "Do NOT weaken or edit the acceptance tests" in fb


def test_an_unmeasurable_look_never_blocks(tmp_path, monkeypatch, capsys):
    """A thin SPA capture must not wedge a build — an unmeasurable gate must not fail."""
    app = _ws(tmp_path)
    monkeypatch.setattr(V, "measure", lambda n, **k: {
        "combined": None, "scores": {}, "skips": {"all": "SPA shell"},
        "missing_tokens": {}})
    assert B._with_ui_parity(lambda: VerifyResult(ok=True, feedback=""), app)().ok
    assert "not measurable" in capsys.readouterr().out


def test_a_crashing_measurement_never_blocks(tmp_path, monkeypatch, capsys):
    app = _ws(tmp_path)

    def boom(n, **k):
        raise RuntimeError("bad manifest")

    monkeypatch.setattr(V, "measure", boom)
    assert B._with_ui_parity(lambda: VerifyResult(ok=True, feedback=""), app)().ok
    assert "not measured" in capsys.readouterr().out


def test_a_non_standard_layout_is_skipped(tmp_path, monkeypatch):
    """measure() resolves paths from <root>/apps/<name>; a temp clone dir cannot."""
    called = []
    monkeypatch.setattr(V, "measure", lambda n, **k: called.append(1))
    odd = tmp_path / "somewhere" / "else"
    odd.mkdir(parents=True)
    assert B._with_ui_parity(lambda: VerifyResult(ok=True, feedback=""), odd)().ok
    assert called == []


def test_the_oracle_is_only_wrapped_for_a_clone():
    """Flow A has no reference, so there is nothing to be parity WITH — the UI term is
    added only when a reference UI was vendored. Asserted structurally because
    build_app's scaffolding is not worth driving for a one-line guard."""
    import inspect

    src = inspect.getsource(B.build_app)
    assert "_with_ui_parity" in src
    wrap = src.index("_with_ui_parity(")
    guard = src.rindex("if ui_dir:", 0, wrap)
    between = src[guard:wrap]
    assert between.count("\n") <= 2, (
        "the UI term must sit directly under `if ui_dir:` — a clone-only guard")


# ---- gate auto-selection ----------------------------------------------------
def test_finish_auto_adds_the_visual_gate_for_a_clone(tmp_path, monkeypatch):
    """Gates are opt-in, so without this the visual gate never ran for a clone — the
    reference UI was captured, vendored, and then never scored."""
    ran: list[str] = []
    monkeypatch.setattr(C, "_run_gate", lambda g, n, a: (ran.append(g), True)[1])
    monkeypatch.setattr(C, "_factory_verify", lambda a: True)
    monkeypatch.setattr("area.verify.visual.has_reference_ui", lambda n, **k: True)
    res = types.SimpleNamespace(passed=True, name="t", spec_dir=tmp_path,
                                app_dir=tmp_path, clarify_needed=False)
    args = argparse.Namespace(target="plain", deploy=False, all=False, tdd=False,
                              open=False, no_e2e=True)
    C._finish(res, args)
    assert "visual" in ran


def test_finish_does_not_add_it_without_a_reference(tmp_path, monkeypatch):
    ran: list[str] = []
    monkeypatch.setattr(C, "_run_gate", lambda g, n, a: (ran.append(g), True)[1])
    monkeypatch.setattr(C, "_factory_verify", lambda a: True)
    monkeypatch.setattr("area.verify.visual.has_reference_ui", lambda n, **k: False)
    res = types.SimpleNamespace(passed=True, name="t", spec_dir=tmp_path,
                                app_dir=tmp_path, clarify_needed=False)
    args = argparse.Namespace(target="plain", deploy=False, all=False, tdd=False,
                              open=False, no_e2e=True)
    C._finish(res, args)
    assert "visual" not in ran
