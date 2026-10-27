"""A lesson gets written down only when something was measured.

This is the one habit taken from Google Research's Harness2 (arXiv:2610.14224): its
improvement library adds no entry when the evidence is insufficient. What differs is
what counts as evidence — Harness2 has no ground-truth verifier and leans on model
judgement over behavioural contrast, while here the gate is `compare()`'s own verdict
over MATCHED tasks. So `unpaired`, `insufficient-data`, `no-data` and `new-profile` all
refuse.

The point is the opposite failure from the one the audit kept finding: `description` and
`notes` were free text nothing verified and nothing read, so they drifted. An entry here
carries its evidence beside the claim — digest, verdict, tasks, sample sizes, deltas —
so a later reader can tell a measured lesson from an asserted one.
"""
import yaml

from area import evals as E
from area import profile as P

TASKS = ("t1", "t2", "t3", "t4", "t5", "t6")

PROFILE_WITH_COMMENTS = """# A heavily commented profile, like every real one.
#
# These comments are the reason `record_experience` appends TEXT instead of re-dumping
# the YAML: `yaml.safe_dump` would delete all of this.

kind: k
description: >-
  Does a thing.
labels:
  - k            # trailing comment
prompt_sources: []
skills: none
"""


def _runs(digest, n, *, kind="k", iters=1, passed=True, cost=1.0, ts0=0.0, tasks=TASKS):
    return [{"ts": ts0 + i, "label": kind, "profile": kind,
             "name": tasks[i % len(tasks)], "profile_digest": digest,
             "outer_iters": iters, "passed": passed, "cost_usd": cost,
             "duration_s": 10.0} for i in range(n)]


def _setup(tmp_path):
    (tmp_path / "k.yaml").write_text(PROFILE_WITH_COMMENTS)
    prof = P.load_profile("k", root=tmp_path)
    assert prof is not None
    return prof.digest


def test_it_refuses_when_nothing_was_measured(tmp_path):
    _setup(tmp_path)
    cases = [
        ([], "no-data"),
        # runs exist, but only against the PREVIOUS version — the current one has never
        # been exercised. Saying "they share no task" would be true and unhelpful.
        (_runs("old", 6), "the current version has no measured runs"),
    ]
    for runs, expected in cases:
        ok, why = E.record_experience("k", "a lesson", runs=runs, root=tmp_path)
        assert ok is False and expected in why, why
    assert "experience:" not in (tmp_path / "k.yaml").read_text()


def test_it_refuses_an_unpaired_comparison(tmp_path):
    """Two versions that ran different work are the case most likely to produce a
    confident-sounding wrong lesson."""
    cur = _setup(tmp_path)
    runs = _runs("old", 6, tasks=("a1", "a2")) + _runs(cur, 6, tasks=("b1", "b2"))
    ok, why = E.record_experience("k", "looks faster", runs=runs, root=tmp_path)
    assert ok is False and "unpaired" in why


def test_it_refuses_too_small_a_sample(tmp_path):
    cur = _setup(tmp_path)
    runs = _runs("old", 2, tasks=("t1",)) + _runs(cur, 2, tasks=("t1",))
    ok, why = E.record_experience("k", "seems better", runs=runs, root=tmp_path)
    assert ok is False and "insufficient-data" in why


def test_it_records_with_the_evidence_attached_and_keeps_the_comments(tmp_path):
    cur = _setup(tmp_path)
    runs = (_runs("old", 6, iters=2, ts0=0) + _runs(cur, 6, iters=1, ts0=100))
    ok, why = E.record_experience("k", "  the  new prompt   converges first-try  ",
                                  runs=runs, root=tmp_path, when="2026-10-27")
    assert ok is True, why

    text = (tmp_path / "k.yaml").read_text()
    # the file must still parse, and still be the commented file it was
    raw = yaml.safe_load(text)
    assert "# trailing comment" in text and "heavily commented profile" in text
    assert len(raw["experience"]) == 1
    e = raw["experience"][0]
    assert e["when"] == "2026-10-27" and e["digest"] == cur
    assert e["verdict"] in E.DECISIVE
    assert sorted(e["tasks"]) == sorted(TASKS)          # measured on matched tasks
    assert e["runs"] == {"current": 6, "previous": 6}
    assert e["deltas"], "an entry with no deltas is an assertion, not evidence"
    assert e["note"] == "the new prompt converges first-try"   # whitespace normalised


def test_recording_does_not_invalidate_what_it_records(tmp_path):
    """The trap this had to avoid: the digest used to hash the whole raw mapping, so
    writing the lesson down would have changed the version it was about and orphaned the
    runs that justified it."""
    cur = _setup(tmp_path)
    runs = (_runs("old", 6, iters=2, ts0=0) + _runs(cur, 6, iters=1, ts0=100))
    assert E.record_experience("k", "a measured lesson", runs=runs, root=tmp_path)[0]
    after = P.load_profile("k", root=tmp_path)
    assert after is not None and after.digest == cur, "recording moved the digest"


def test_a_second_entry_appends_under_the_same_key(tmp_path):
    cur = _setup(tmp_path)
    runs = (_runs("old", 6, iters=2, ts0=0) + _runs(cur, 6, iters=1, ts0=100))
    assert E.record_experience("k", "first", runs=runs, root=tmp_path, when="2026-10-01")[0]
    assert E.record_experience("k", "second", runs=runs, root=tmp_path, when="2026-10-02")[0]
    raw = yaml.safe_load((tmp_path / "k.yaml").read_text())
    assert [e["note"] for e in raw["experience"]] == ["first", "second"]
    assert (tmp_path / "k.yaml").read_text().count("experience:") == 1


def test_the_index_is_newest_first_and_names_the_kind(tmp_path):
    cur = _setup(tmp_path)
    runs = (_runs("old", 6, iters=2, ts0=0) + _runs(cur, 6, iters=1, ts0=100))
    E.record_experience("k", "older", runs=runs, root=tmp_path, when="2026-01-01")
    E.record_experience("k", "newer", runs=runs, root=tmp_path, when="2026-09-09")
    idx = E.experience_index(root=tmp_path)
    assert [e["note"] for e in idx] == ["newer", "older"]
    assert all(e["kind"] == "k" for e in idx)
    out = E.experience_text(idx)
    assert "newer" in out and "2026-09-09" in out and "evidence:" in out


def test_an_empty_note_is_refused(tmp_path):
    cur = _setup(tmp_path)
    runs = (_runs("old", 6, iters=2, ts0=0) + _runs(cur, 6, iters=1, ts0=100))
    ok, why = E.record_experience("k", "   ", runs=runs, root=tmp_path)
    assert ok is False and "empty" in why
