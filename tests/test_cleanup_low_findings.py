"""Cleanup of the deep-audit LOW/dormant findings: B11, B13, B15, B16, B17.

B18 (ui_capture sorts before the file cap) is a determinism fix not amenable to a
red test (it depends on filesystem iteration order); B14 (chunked scan of large text) is
deferred — see docs/deep-audit-2026-10-28.md.
"""
import pytest


# ── B11 ── iterate must expose --audit-level, so provenance records the level enforced
def test_b11_iterate_accepts_audit_level():
    from area.cli import _build_parser

    ns = _build_parser().parse_args(
        ["iterate", "app", "a change", "--audit", "--audit-level", "moderate"])
    assert ns.audit_level == "moderate"


# ── B13 ── nfr must FAIL CLOSED under --strict when nothing could be measured
def test_b13_nfr_fails_closed_under_strict_with_no_metrics(monkeypatch, tmp_path):
    import area.verify.nfr as N

    (tmp_path / "apps" / "x").mkdir(parents=True)
    monkeypatch.setattr(N, "load_budget", lambda name, strict=False, root=None: ({}, True))
    monkeypatch.setattr(N, "measure", lambda app, run_build=False: {})
    monkeypatch.setattr(N, "evaluate", lambda metrics, budget: [])
    assert N.nfr_verify("x", strict=True, root=tmp_path) is False


def test_b13_nfr_skips_ok_when_advisory(monkeypatch, tmp_path):
    import area.verify.nfr as N

    (tmp_path / "apps" / "x").mkdir(parents=True)
    monkeypatch.setattr(N, "load_budget", lambda name, strict=False, root=None: ({}, False))
    monkeypatch.setattr(N, "measure", lambda app, run_build=False: {})
    monkeypatch.setattr(N, "evaluate", lambda metrics, budget: [])
    assert N.nfr_verify("x", strict=False, root=tmp_path) is True


# ── B15 ── seed PII strip must catch common field-name variants, not only exact matches
@pytest.mark.parametrize("field", [
    "email_address", "phoneNumber", "customerName", "firstName",
    "billing_address", "user.email"])
def test_b15_pii_variants_are_dropped(field):
    from area.seed import is_pii_field

    assert is_pii_field(field), field


@pytest.mark.parametrize("field", ["product_id", "title", "sku", "quantity"])
def test_b15_non_pii_kept(field):
    from area.seed import is_pii_field

    assert not is_pii_field(field), field


# ── B16 ── record_experience must judge on the same declared task set as the gate
def test_b16_record_experience_narrows_to_declared_tasks(monkeypatch):
    import area.evals as E

    seen: dict = {}
    monkeypatch.setattr(E, "compare", lambda kind, **k: (
        seen.update(k), {"verdict": "insufficient-data", "reason": "x"})[1])
    monkeypatch.setattr(E, "load_task_set", lambda root=None: {"t1", "t2"})
    E.record_experience("builder", "a note", runs=[])
    assert seen.get("only_tasks") == {"t1", "t2"}


# ── B17 ── a declared "/" route must not make routes_unquoted match every slash (dormant)
def test_b17_slash_route_does_not_mask_an_undeclared_path():
    from area.spec.models import (
        Acceptance,
        AcceptanceCriterion,
        Route,
        Spec,
        routes_unquoted,
    )

    spec = Spec(name="c", summary="s", routes=[Route(path="/")])
    acc = Acceptance(criteria=[AcceptanceCriterion(
        id="AC-1", feature="f", given="a user", when="they visit /admin/secret",
        then="it loads")])
    assert routes_unquoted(spec, acc) == ["AC-1"]
