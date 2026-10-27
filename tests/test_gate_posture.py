"""Round-3 audit remediation — gate posture.
#7 the audit's injection-class tier-2 findings (XSS / eval / SQL-injection) now
BLOCK by default (not advisory-until-strict); shell-exec / weak-random stay
advisory; `block_injection=False` downgrades the injection class.
#12 the NFR gate FAILs (not silent-passes) when a COMMITTED budget names a metric
that produced no measurement."""
import area.verify.audit as A
import area.verify.nfr as N

_INJ = "SQL built via string interpolation — injection risk"
_SHELL = "shell exec — command-injection risk"
_RAND = "Math.random() — not cryptographically secure (use crypto)"


# ---- #7: injection class blocks by default ------------------------------------

def test_injection_msgs_membership():
    assert _INJ in A._INJECTION_MSGS
    assert "React XSS sink — dangerouslySetInnerHTML" in A._INJECTION_MSGS
    assert "eval() — code-injection risk" in A._INJECTION_MSGS
    assert _SHELL not in A._INJECTION_MSGS     # shell-exec stays advisory
    assert _RAND not in A._INJECTION_MSGS


def test_injection_blocks_by_default():
    findings = [("lib/q.ts", 3, _INJ)]
    blocking = A._blocking_findings(findings, strict=False, block_injection=True)
    assert blocking == findings                # blocks with no --strict


def test_non_injection_is_advisory_by_default():
    findings = [("lib/x.ts", 1, _SHELL), ("lib/y.ts", 2, _RAND)]
    assert A._blocking_findings(findings, strict=False, block_injection=True) == []
    # ...but --strict blocks everything
    assert A._blocking_findings(findings, strict=True, block_injection=True) == findings


def test_no_block_injection_downgrades():
    findings = [("lib/q.ts", 3, _INJ)]
    assert A._blocking_findings(findings, strict=False, block_injection=False) == []
    # still blocks under --strict even when injection-blocking is off
    assert A._blocking_findings(findings, strict=True, block_injection=False) == findings


def test_mixed_only_injection_blocks_by_default():
    findings = [("a.ts", 1, _INJ), ("b.ts", 2, _SHELL)]
    blocking = A._blocking_findings(findings, strict=False, block_injection=True)
    assert blocking == [("a.ts", 1, _INJ)]


# ---- #12: committed-but-unmeasured NFR budget FAILs ---------------------------

def _app(tmp_path, name="app1"):
    (tmp_path / "apps" / name).mkdir(parents=True)
    spec = tmp_path / "specs" / name
    spec.mkdir(parents=True)
    return spec


def test_nfr_fails_on_committed_unmeasured_budget(tmp_path, monkeypatch):
    spec = _app(tmp_path)
    (spec / "nfr.yaml").write_text("bundle_kib: 100\n")      # committed → blocking
    monkeypatch.setattr(N, "measure", lambda app, **k: {})   # nothing measurable
    # was a silent "skipped → PASS"; now a committed budget we can't verify FAILs
    assert N.nfr_verify("app1", root=tmp_path) is False


def test_nfr_passes_when_committed_metric_is_measured(tmp_path, monkeypatch):
    spec = _app(tmp_path)
    (spec / "nfr.yaml").write_text("bundle_kib: 100\n")
    monkeypatch.setattr(N, "measure", lambda app, **k: {"bundle_kib": 50})
    assert N.nfr_verify("app1", root=tmp_path) is True


def test_nfr_advisory_unmeasured_still_skips(tmp_path, monkeypatch):
    _app(tmp_path)   # no nfr.yaml → defaults → advisory (not blocking)
    monkeypatch.setattr(N, "measure", lambda app, **k: {})
    assert N.nfr_verify("app1", root=tmp_path) is True   # advisory → skip, not fail
