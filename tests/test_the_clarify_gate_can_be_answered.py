"""The --clarify gate had a STOP and no RESUME.

It printed "Confirm/override then re-run", but nothing the operator could do satisfied
it. Measured on a real app (`expenses`, 2026-10-28) over three runs:

  * `--expect` is text appended to the EXTRACTION prompt; it never reaches the gate,
    and giving the extractor more detail makes the independent reviewer ask DEEPER
    questions — 8 -> 2 -> 11 material assumptions across the three attempts;
  * editing `material: false` in `assumptions.yaml` is destroyed, because the
    extractor rewrites that file every run (proven: attempt 2's two questions are
    absent from attempt 3's file, and `append_assumptions` dedupes by question text,
    so a merge would have kept them);
  * no `clarify`/`confirm` verb existed among the 32 handlers;
  * so the only exit was `--no-clarify`, which removes the gate instead of answering
    it — while each attempt cost a fresh extraction plus an unpriced review.

These pin the resume. docs/harness2-gap-assessment.md / self-audit M10.
"""
import yaml

import pytest

from area import pipeline as P
from area.provenance import spec_digest
from area.spec import clarify as C


def _spec(tmp_path, *, material=2, nonmaterial=1):
    d = tmp_path / "specs" / "app1"
    d.mkdir(parents=True)
    (d / "spec.yaml").write_text("name: app1\nsummary: a thing\n")
    (d / "acceptance.yaml").write_text("criteria: []\n")
    items = [{"question": f"material q{i}?", "assumption": f"guess {i}",
              "material": True} for i in range(material)]
    items += [{"question": f"minor q{i}?", "assumption": "x", "material": False}
              for i in range(nonmaterial)]
    (d / "assumptions.yaml").write_text(yaml.safe_dump({"assumptions": items}))
    return d


def test_the_gate_reports_only_material_questions(tmp_path):
    d = _spec(tmp_path, material=2, nonmaterial=3)
    assert len(C.open_questions(d)) == 2
    assert P._clarify_gate(tmp_path, "app1", True) == C.open_questions(d)


def test_the_gate_is_silent_once_this_spec_is_confirmed(tmp_path):
    d = _spec(tmp_path)
    assert C.open_questions(d), "nothing to confirm; the test proves nothing"
    C.confirm(d, C.open_questions(d))
    assert C.open_questions(d) == []
    assert P._clarify_gate(tmp_path, "app1", True) == []


def test_recording_a_confirmation_does_not_change_the_digest_it_anchors_to(tmp_path):
    """`clarified.yaml` must stay out of `provenance._MATERIALS`, or confirming would
    expire itself."""
    d = _spec(tmp_path)
    before = spec_digest(d)
    C.confirm(d, C.open_questions(d))
    assert spec_digest(d) == before
    assert C.is_current(d) is True


def test_changing_the_spec_expires_the_confirmation(tmp_path):
    """The whole point of anchoring on the digest: a human confirmed THAT spec."""
    d = _spec(tmp_path)
    C.confirm(d, C.open_questions(d))
    assert C.is_current(d) is True

    (d / "spec.yaml").write_text("name: app1\nsummary: something ELSE\n")
    assert C.is_current(d) is False
    assert len(C.open_questions(d)) == 2, "the gate must ask again"


def test_a_confirmation_names_what_it_covered(tmp_path):
    """A confirmation that does not say what was accepted is not evidence."""
    d = _spec(tmp_path, material=2)
    qs = C.open_questions(d)
    C.confirm(d, qs)
    rec = C.load_record(d)
    assert [q["question"] for q in rec["questions"]] == [q["question"] for q in qs]
    assert all(q["assumed"] for q in rec["questions"])
    assert rec["spec_digest"] == spec_digest(d)


def test_a_typed_answer_is_recorded_and_becomes_authoritative_input(tmp_path):
    d = _spec(tmp_path, material=2)
    C.confirm(d, C.open_questions(d), answers={1: "store it in cents, integer only"})
    block = C.answers_block(d)
    assert "store it in cents" in block
    assert "do not re-guess" in block
    assert "material q1?" in block
    assert "material q0?" not in block, "an un-answered question leaked in as an answer"


def test_accepting_the_agents_own_guesses_adds_nothing_for_the_extractor(tmp_path):
    """--confirm-all means "go ahead", not "the human decided this". Feeding the
    agent's own assumption back as an ANSWER would dress a guess up as a decision."""
    d = _spec(tmp_path)
    C.confirm(d, C.open_questions(d))
    assert C.answers_block(d) == ""


def test_an_unreadable_or_absent_record_is_not_a_confirmation(tmp_path):
    d = _spec(tmp_path)
    assert C.is_current(d) is False
    (d / C.CLARIFIED).write_text("{ not yaml")
    assert C.load_record(d) == {} and C.is_current(d) is False
    (d / C.CLARIFIED).write_text(yaml.safe_dump({"confirmed": False}))
    assert C.is_current(d) is False


def test_a_record_for_a_different_spec_is_not_a_confirmation(tmp_path):
    """Hand-written or copied-in records must not pass."""
    d = _spec(tmp_path)
    (d / C.CLARIFIED).write_text(yaml.safe_dump(
        {"confirmed": True, "spec_digest": "sha256:" + "0" * 64, "questions": []}))
    assert C.is_current(d) is False
    assert len(C.open_questions(d)) == 2


def test_no_clarify_still_bypasses_entirely(tmp_path):
    """The old escape hatch keeps working — this adds a way to answer, it does not
    remove the way to opt out."""
    _spec(tmp_path)
    assert P._clarify_gate(tmp_path, "app1", False) == []


# ---- reuse: what makes a confirmation usable at all ---------------------------

def test_reuse_loads_the_confirmed_spec_instead_of_regenerating_it(tmp_path):
    """Without this, re-running after confirming would re-extract — and because the
    extractor is an LLM the new spec has a different digest, expiring the
    confirmation the human just gave. It would also mean the spec that was reviewed
    is not the spec that gets built."""
    from area.spec.extract import extract_spec

    d = _spec(tmp_path)
    (d / "spec.yaml").write_text("name: app1\nsummary: the reviewed one\n")
    (d / "acceptance.yaml").write_text(
        "criteria:\n- id: AC-1\n  feature: f\n  given: g\n  when: w\n  then: t\n")

    spec, acc = extract_spec("ignored requirement", d, reuse=True)
    assert spec.summary == "the reviewed one"
    assert [c.id for c in acc.criteria] == ["AC-1"]


def test_reuse_refuses_when_there_is_nothing_to_reuse(tmp_path):
    from area.spec.extract import extract_spec

    with pytest.raises(RuntimeError, match="no spec to reuse"):
        extract_spec("req", tmp_path / "specs" / "nope", reuse=True)


def test_the_resume_hint_names_the_right_command_for_a_clone(tmp_path):
    """A hint that loses parity is worse than no hint.

    `area run` has no `reference`, so building a clone's confirmed spec with it yields a
    plain app from that spec — no parity oracle, no UI term in the build oracle, and
    GREEN. The hint printed after `--confirm-all` said exactly that for every flow,
    which recreates M17's failure as advice. Caught by reading what the command actually
    printed on a real clone, not by a test.
    """
    from area.cli import _resume_hint

    plain = tmp_path / "specs" / "a"
    plain.mkdir(parents=True)
    assert _resume_hint(plain, "a") == "area run --name a --use-spec"

    clone = tmp_path / "specs" / "b"
    (clone / "_sample").mkdir(parents=True)     # what makes a spec dir a clone's
    hint = _resume_hint(clone, "b")
    assert hint.startswith("area clone "), hint
    assert "--use-spec" in hint and "--tdd" in hint
    assert "area run" not in hint, "a clone was pointed at the non-parity command"
