"""The audit gate must GRADE what it prints.

Regression test for a false green: tier-2's blocking findings were measured once up
front and re-checked only under `strict`, while the fix loop ran against a
tier-1-only oracle. With tier-1 already green the loop therefore passed on attempt 1,
and `static_audit` printed `❌ BLOCK <file>:<line>` for every injection sink and then
`audit: ✅ PASS` — and provenance recorded the gate as `blocking:true, blocked:false`.
"""
import area.verify.audit as A
from area.engine import VerifyResult


def _app(tmp_path, body: str):
    """A minimal app tree with one source file, plus audit's WORKSPACE layout."""
    app = tmp_path / "apps" / "x"
    (app / "app").mkdir(parents=True)
    (app / "app" / "page.tsx").write_text(body)
    return app


def _green_tier1(monkeypatch):
    """Tier 1 (tsc + npm audit + secrets) passes — no node/npm needed."""
    monkeypatch.setattr(A, "command_verifier",
                        lambda *a, **k: lambda: VerifyResult(True, "tier-1 ok"))


def _lazy_agent(monkeypatch, fixer=None):
    """A fix loop whose agent does nothing (or applies `fixer`), then reports success
    the way `run_until` does — the shape that used to be taken at face value."""
    monkeypatch.setattr(A, "build_agent", lambda *a, **k: type(
        "Ag", (), {"close": lambda self: None})())

    def fake_run_until(agent, app, task, oracle, **kw):
        if fixer:
            fixer(app)
        return oracle().ok, 1

    monkeypatch.setattr(A, "run_until", fake_run_until)


INJECTION = 'export default function P(){return <div dangerouslySetInnerHTML={{__html: q}} />}\n'
CLEAN = 'export default function P(){return <div>{q}</div>}\n'


def test_injection_sink_cannot_pass_in_the_default_posture(tmp_path, monkeypatch, capsys):
    """tier-1 green + an unfixed injection sink + fix=True ⇒ the gate must FAIL.
    This is the exact combination that used to return True."""
    app = _app(tmp_path, INJECTION)
    monkeypatch.setattr(A, "WORKSPACE", tmp_path)
    _green_tier1(monkeypatch)
    _lazy_agent(monkeypatch)                      # agent changes nothing

    assert A.advisory_scan(app), "fixture must actually trip tier-2"
    assert A.static_audit("x", fix=True) is False  # default strict=False

    out = capsys.readouterr().out
    assert "BLOCK" in out and "✅ PASS" not in out  # never both


def test_the_gate_passes_once_the_sink_is_actually_gone(tmp_path, monkeypatch):
    """The oracle must RE-MEASURE, not just refuse: an agent that really removes the
    sink gets a pass. Otherwise the fix above would be a gate that can never go green."""
    _app(tmp_path, INJECTION)
    monkeypatch.setattr(A, "WORKSPACE", tmp_path)
    _green_tier1(monkeypatch)
    _lazy_agent(monkeypatch,
                fixer=lambda app: (app / "app" / "page.tsx").write_text(CLEAN))

    assert A.static_audit("x", fix=True) is True


def test_advisory_only_findings_still_pass_without_strict(tmp_path, monkeypatch):
    """The posture is unchanged for the non-injection classes: weak-random is advisory,
    so it must not start blocking just because tier-2 moved into the oracle."""
    app = _app(tmp_path, "const id = Math.random().toString(36)\n")
    monkeypatch.setattr(A, "WORKSPACE", tmp_path)
    _green_tier1(monkeypatch)

    findings = A.advisory_scan(app)
    assert findings, "fixture must trip tier-2"
    assert not A._blocking_findings(findings, strict=False, block_injection=True)
    assert A.static_audit("x", fix=False) is True
    # ... and --strict promotes the very same finding to blocking
    assert A.static_audit("x", fix=False, strict=True) is False


def test_block_injection_false_downgrades_to_advisory(tmp_path, monkeypatch):
    """`block_injection=False` is the documented escape hatch; it must still work."""
    _app(tmp_path, INJECTION)
    monkeypatch.setattr(A, "WORKSPACE", tmp_path)
    _green_tier1(monkeypatch)
    assert A.static_audit("x", fix=False, block_injection=False) is True
