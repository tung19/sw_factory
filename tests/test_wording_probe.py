"""Tests for area.wording_probe — the cheap gate's attestation ledger.

Every test patches `area.wording_probe.WORKSPACE` to a tmp dir, so the real
`WORKSPACE/.area/wording-probes.jsonl` is never written (cf.
test_the_suite_never_writes_the_real_ledger).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from area import wording_probe as wp


@pytest.fixture
def ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(wp, "WORKSPACE", tmp_path)
    return tmp_path


def test_missing_before_any_record(ws: Path) -> None:
    assert wp.status_for("holdout-author", "sha256:abc") == "missing"
    assert wp.latest_for("holdout-author", "sha256:abc") is None


def test_record_then_read_roundtrip(ws: Path) -> None:
    wp.record("holdout-author", "sha256:abc", "binds", "subagent complied 5/5", reps=5)
    assert wp.status_for("holdout-author", "sha256:abc") == "recorded"
    row = wp.latest_for("holdout-author", "sha256:abc")
    assert row is not None
    assert row["verdict"] == "binds"
    assert row["reps"] == 5
    assert (ws / ".area" / "wording-probes.jsonl").exists()


def test_weak_is_not_recorded_status(ws: Path) -> None:
    wp.record("builder", "sha256:d1", "weak", "3/5 scattered", reps=5)
    assert wp.status_for("builder", "sha256:d1") == "weak"


def test_inconclusive_verdict(ws: Path) -> None:
    # A confounded run (no valid control) is neither 'recorded' nor 'weak'.
    wp.record("builder", "sha256:z", "inconclusive", "control saw the rule via CLAUDE.md", reps=10)
    assert wp.status_for("builder", "sha256:z") == "inconclusive"
    row = wp.latest_for("builder", "sha256:z")
    assert row is not None and row["verdict"] == "inconclusive"


def test_attestation_is_keyed_to_digest(ws: Path) -> None:
    # The spine: a probe of the OLD wording cannot vouch for a NEW (changed) digest.
    wp.record("builder", "sha256:OLD", "binds", "ok", reps=5)
    assert wp.status_for("builder", "sha256:OLD") == "recorded"
    assert wp.status_for("builder", "sha256:NEW") == "missing"


def test_latest_wins_on_same_key(ws: Path) -> None:
    wp.record("auditor", "sha256:x", "weak", "first", reps=5)
    wp.record("auditor", "sha256:x", "binds", "second, after tightening", reps=6)
    row = wp.latest_for("auditor", "sha256:x")
    assert row is not None and row["verdict"] == "binds" and row["reps"] == 6
    assert wp.status_for("auditor", "sha256:x") == "recorded"


def test_torn_line_is_ignored_not_fatal(ws: Path) -> None:
    led = ws / ".area" / "wording-probes.jsonl"
    led.parent.mkdir(parents=True, exist_ok=True)
    led.write_text('{"kind": "a", "digest": "d", "verdict": "binds"}\n{ broken\n',
                   encoding="utf-8")
    assert wp.status_for("a", "d") == "recorded"


def test_status_of_kind_uses_current_digest(ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wp, "current_digest", lambda kind, root=None: "sha256:live")
    assert wp.status_of_kind("holdout-author") == "missing"
    wp.record("holdout-author", "sha256:live", "binds", "ok", reps=5)
    assert wp.status_of_kind("holdout-author") == "recorded"


def test_four_verdicts_map_to_four_distinct_statuses(ws: Path) -> None:
    # Mutation guard (superpowers:writing-good-tests): if status_for ever collapsed two
    # verdicts, this fails. The ledger must DISCRIMINATE, or the gate is theater.
    wp.record("k", "sha256:binds", "binds", "e", reps=5)
    wp.record("k", "sha256:weak", "weak", "e", reps=5)
    wp.record("k", "sha256:incon", "inconclusive", "e", reps=5)
    seen = {
        wp.status_for("k", "sha256:binds"),
        wp.status_for("k", "sha256:weak"),
        wp.status_for("k", "sha256:incon"),
        wp.status_for("k", "sha256:never-recorded"),
    }
    assert seen == {"recorded", "weak", "inconclusive", "missing"}


def test_report_lists_each_kind_once(ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import area.profile as prof

    monkeypatch.setattr(prof, "all_profiles", lambda root=None: {"k1": object(), "k2": object()})
    monkeypatch.setattr(wp, "current_digest", lambda kind, root=None: f"sha256:{kind}")
    wp.record("k1", "sha256:k1", "binds", "ok", reps=5)
    text = wp.report()
    assert "k1" in text and "recorded" in text
    assert "k2" in text and "missing" in text
