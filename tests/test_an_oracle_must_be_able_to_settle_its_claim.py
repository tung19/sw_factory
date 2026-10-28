"""AREA enforced the oracle's INDEPENDENCE and never measured its STRENGTH.

The spine is "quality <= strength + independence of the oracle". Independence is
enforced hard: a separate agent authors the suite from the spec alone, it is
checksum-frozen, and the build oracle refuses if a locked file was modified or did
not execute. Nothing measured whether a test can settle the claim it makes.

Found by building a real app. `expenses` AC-14 asserted "the app makes no outbound
network requests" — a property of the RUNNING system — and the locked holdout
"verified" it by grepping source for HTTP client names. It reported PASS while
`next telemetry status` said `Enabled` (false negative), and on re-run it FAILED on a
documentation URL inside a comment in a generated file (false positive). Maximally
independent, nearly powerless, and `_authoring_oracle` accepted it because its
coverage check is "the AC id appears in the test text".

Three layers, following IEEE 1233 (verifiability is an attribute of the requirement,
proven by execution / inspection / demonstration / analysis) and the practice of
reporting an "unable to verify" result separately from the pass rate:

  1. the criterion states its method (`verify_by`);
  2. the authoring oracle checks the test does that KIND of work — blocking under
     --strict, so the decision is a term in the loop's verifier and not a note beside
     it;
  3. the verdict is reported and carried into provenance, so "oracle green" is
     qualified rather than overstated.
"""
import yaml


from area.spec.models import VERIFY_METHODS, AcceptanceCriterion, load_acceptance
from area.verify import strength as S
from area.verify.holdout import _authoring_oracle

# The shape a holdout test has when it drives the app, and when it only reads it.
_DRIVES = """
import { describe, it, expect } from 'vitest'
describe('AC-1 adds an expense', () => {
  it('stores it', async () => {
    const mod = await import('../../lib/expenses')
    expect(mod.add({ cents: 1050 }).cents).toBe(1050)
  })
})
"""
_GREPS = """
import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
describe('AC-2 makes no outbound network requests', () => {
  it('has no http client', () => {
    const src = fs.readFileSync('app/page.tsx', 'utf8')
    expect(/axios/.test(src)).toBe(false)
  })
})
"""


def _acc(*pairs):
    return yaml.safe_dump({"criteria": [
        {"id": i, "feature": "f", "given": "g", "when": "w", "then": "t",
         **({"verify_by": m} if m else {})} for i, m in pairs]})


# ---- layer 1: the criterion can state its method ------------------------------

def test_the_method_is_optional_so_existing_specs_still_load(tmp_path):
    """`taskboard`, `invoice_mgr`, `fb_incept` and `expenses` predate this field.
    An unstated method must read as unstated — never defaulted to one nobody chose."""
    c = AcceptanceCriterion(id="AC-1", feature="f", given="g", when="w", then="t")
    assert c.verify_by is None

    p = tmp_path / "acceptance.yaml"
    p.write_text(_acc(("AC-1", None)))
    assert load_acceptance(p).criteria[0].verify_by is None


def test_the_four_methods_are_the_ieee_set():
    assert VERIFY_METHODS == ("execution", "inspection", "demonstration", "analysis")


# ---- layer 2: the detector, on the real shapes --------------------------------

def test_a_runtime_claim_proven_by_grepping_source_is_unable_to_verify():
    v = S.classify(yaml.safe_load(_acc(("AC-2", "execution")))["criteria"], _GREPS)
    assert v["AC-2"] == S.MISMATCH
    assert S.weak(v) == ["AC-2"]


def test_the_same_test_is_fine_when_the_criterion_claims_inspection():
    """A source grep is a legitimate oracle for "no dependency on X". The defect is
    the MISMATCH, not the technique."""
    v = S.classify(yaml.safe_load(_acc(("AC-2", "inspection")))["criteria"], _GREPS)
    assert v["AC-2"] == S.VERIFIED


def test_a_test_that_drives_the_app_satisfies_execution():
    v = S.classify(yaml.safe_load(_acc(("AC-1", "execution")))["criteria"], _DRIVES)
    assert v["AC-1"] == S.VERIFIED


def test_an_unstated_method_is_reported_as_unstated_not_as_weak():
    v = S.classify(yaml.safe_load(_acc(("AC-1", None)))["criteria"], _DRIVES)
    assert v["AC-1"] == S.UNSTATED
    assert S.weak(v) == [] and S.unstated(v) == ["AC-1"]


def test_a_criterion_no_test_mentions_is_uncovered():
    v = S.classify(yaml.safe_load(_acc(("AC-99", "execution")))["criteria"], _DRIVES)
    assert v["AC-99"] == S.UNCOVERED


def test_the_block_is_scoped_to_the_criterion_not_the_whole_file():
    """One file often holds several criteria. A file that drives the app SOMEWHERE
    must not launder a grep-only criterion inside it."""
    both = _DRIVES + _GREPS
    v = S.classify(
        yaml.safe_load(_acc(("AC-1", "execution"), ("AC-2", "execution")))["criteria"],
        both)
    assert v["AC-1"] == S.VERIFIED
    assert v["AC-2"] == S.MISMATCH, "the grep-only block borrowed the other's strength"


def test_an_unparseable_structure_guesses_toward_fine():
    """A detector that guesses wrong must guess toward "fine": a false block on an
    honest suite costs more than a missed weak one."""
    v = S.classify(yaml.safe_load(_acc(("AC-1", "execution")))["criteria"],
                   "AC-1 mentioned with no describe and no braces at all")
    assert v["AC-1"] == S.VERIFIED


def test_the_report_reads_like_the_cost_gate():
    v = S.classify(
        yaml.safe_load(_acc(("AC-1", "execution"), ("AC-2", "execution")))["criteria"],
        _DRIVES + _GREPS)
    r = S.report(v)
    assert "of 2 criteria verified" in r and "UNABLE TO VERIFY" in r and "AC-2" in r


# ---- layer 2 wiring: blocking only under --strict -----------------------------

def _holdout(tmp_path, body):
    h = tmp_path / "__tests__" / "_holdout"
    h.mkdir(parents=True)
    (h / "ac.test.ts").write_text(body)
    (h / "CONTRACT.md").write_text("lib/expenses: add()\n")
    return h


def test_a_weak_oracle_is_reported_but_does_not_block_by_default(tmp_path, capsys):
    h = _holdout(tmp_path, _GREPS)
    ok, _ = _authoring_oracle(h, _acc(("AC-2", "execution")), require_contract=True)
    assert ok is True, "a weak criterion must not fail an honest build by default"
    assert "oracle strength" in capsys.readouterr().out


def test_strict_makes_it_block_and_says_what_to_do(tmp_path):
    h = _holdout(tmp_path, _GREPS)
    ok, feedback = _authoring_oracle(h, _acc(("AC-2", "execution")),
                                     require_contract=True, strict=True)
    assert ok is False
    assert "AC-2" in feedback and "public surface" in feedback


def test_strict_passes_a_suite_whose_tests_match_their_claims(tmp_path):
    h = _holdout(tmp_path, _DRIVES)
    ok, feedback = _authoring_oracle(h, _acc(("AC-1", "execution")),
                                     require_contract=True, strict=True)
    assert ok is True, feedback


def test_a_malformed_acceptance_file_never_crashes_the_authoring_oracle(tmp_path):
    h = _holdout(tmp_path, _DRIVES)
    ok, _ = _authoring_oracle(h, "{ not: [valid", require_contract=True, strict=True)
    assert isinstance(ok, bool)


# ---- layer 3: provenance carries the verdict ----------------------------------

def test_provenance_records_which_criteria_could_be_settled(tmp_path):
    from area.provenance import write_provenance

    app = tmp_path / "apps" / "a"
    _holdout(app, _DRIVES + _GREPS)
    sd = tmp_path / "specs" / "a"
    sd.mkdir(parents=True)
    (sd / "acceptance.yaml").write_text(
        _acc(("AC-1", "execution"), ("AC-2", "execution")))

    rec = write_provenance(app, name="a", target="plain", gates={}, spec_dir=sd)
    assert rec["oracle"]["criteria"] == 2
    assert rec["oracle"]["unableToVerify"] == ["AC-2"]
    assert rec["oracle"]["methodUnstated"] == []


def test_provenance_stays_quiet_when_there_is_no_suite_to_judge(tmp_path):
    from area.provenance import write_provenance

    app = tmp_path / "apps" / "b"
    app.mkdir(parents=True)
    rec = write_provenance(app, name="b", target="plain", gates={})
    assert rec["oracle"] == {}
