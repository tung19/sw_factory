"""PR8 Phase 0 — the AI-DLC Inception artifact contract (docs/aidlc-artifact
-contract.md). Covers the adapter's deterministic ingest (load_aidlc_artifacts)
and keeps the golden fixture contract-compliant. The agent TRANSLATION
(spec_from_aidlc) is validated by dogfood runs, not here (agent-free suite)."""
import re
from pathlib import Path

import pytest

import area.intake.aidlc as A

FIXTURE = Path(__file__).parent / "fixtures" / "aidlc" / "link-shortener"


# ---- load_aidlc_artifacts: the frozen ingest behavior ---------------------------

def test_load_fixture_blobs_all_files_in_sorted_order():
    blob = A.load_aidlc_artifacts(FIXTURE)
    for name in ("01-intent.md", "02-user-stories.md",
                 "03-units-of-work.md", "04-testing-posture.md"):
        assert f"=== {name} ===" in blob
    # sorted read → intent before testing posture
    assert blob.index("01-intent.md") < blob.index("04-testing-posture.md")
    # key content survived
    assert "UoW-1" in blob and "Given" in blob and "As a sharer" in blob


def test_load_single_file():
    blob = A.load_aidlc_artifacts(FIXTURE / "03-units-of-work.md")
    assert "=== 03-units-of-work.md ===" in blob and "UoW-4" in blob


def test_skips_non_artifact_extensions(tmp_path):
    (tmp_path / "keep.md").write_text("# UoW-1 keep me")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG not text")
    blob = A.load_aidlc_artifacts(tmp_path)
    assert "keep me" in blob and "logo.png" not in blob


def test_caps_at_max_chars(tmp_path):
    (tmp_path / "big.md").write_text("x" * 5000)
    blob = A.load_aidlc_artifacts(tmp_path, max_chars=500)
    assert len(blob) <= 500


def test_missing_path_raises(tmp_path):
    with pytest.raises(RuntimeError):
        A.load_aidlc_artifacts(tmp_path / "nope")


def test_no_artifact_files_raises(tmp_path):
    (tmp_path / "image.png").write_bytes(b"x")
    with pytest.raises(RuntimeError):
        A.load_aidlc_artifacts(tmp_path)


def test_empty_files_yield_header_only_blob(tmp_path):
    # Frozen behavior: an empty artifact FILE still contributes its `=== … ===`
    # header, so the blob is non-empty and no error is raised. (The front-end is
    # responsible for putting real content in each file — see the contract doc.)
    (tmp_path / "a.md").write_text("")
    blob = A.load_aidlc_artifacts(tmp_path)
    assert blob == "=== a.md ==="


# ---- the fixture is the executable example of the contract ----------------------

def _uow_ids(text: str) -> set[str]:
    return set(re.findall(r"UoW-\d+", text))


def test_fixture_every_uow_has_a_testing_posture_statement():
    uow = _uow_ids((FIXTURE / "03-units-of-work.md").read_text())
    posture = (FIXTURE / "04-testing-posture.md").read_text()
    # every UoW must be referenced by ≥1 acceptance statement (contract rule 1+2)
    tagged = {u for u in uow if re.search(rf"^- {re.escape(u)}:", posture, re.M)}
    assert uow and tagged == uow, f"UoW without a tagged testing-posture statement: {uow - tagged}"


def test_fixture_testing_posture_is_given_when_then():
    for line in (FIXTURE / "04-testing-posture.md").read_text().splitlines():
        if re.match(r"^- UoW-\d+:", line):
            assert all(k in line for k in ("Given", "When", "Then")), f"not G/W/T: {line}"


def test_fixture_user_stories_have_role_capability_value():
    for line in (FIXTURE / "02-user-stories.md").read_text().splitlines():
        if re.match(r"^- \*\*US-\d+\*\*", line):
            assert "As a" in line and "I want" in line and "so that" in line, line
