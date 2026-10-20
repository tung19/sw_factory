"""PR8 Phase 1 — the governed Inception engine. The agent PROPOSE and the human
APPROVE steps are injected here (canned text / auto-accept), so the governance
orchestration, prompt composition, artifact writing, contract validation and
evidence trail are all covered WITHOUT an agent or a human."""
import json
from pathlib import Path

import area.inception.engine as E

FIXTURE = Path(__file__).parent / "fixtures" / "aidlc" / "link-shortener"

# Canned, contract-compliant bolt content keyed by bolt.key.
CANNED = {
    "intent": "# Intent\n## Problem\nx\n## Goals\n- g\n",
    "stories": "- **US-1**: As a user, I want x, so that y.\n",
    "units": "- **UoW-1 — do-x**: does x. (covers US-1)\n",
    "posture": "- UoW-1: Given a, When b, Then c.\n",
}


def _canned_propose(bolt, prompt):
    return CANNED[bolt.key]


def _accept(bolt, proposed):
    return proposed


# ---- bolt_prompt (pure) ---------------------------------------------------------

def test_bolt_prompt_embeds_requirement_filename_instruction(tmp_path):
    p = E.bolt_prompt(E.BOLTS[0], "build a thing", tmp_path)
    assert "build a thing" in p
    assert "01-intent.md" in p
    assert "Problem" in p  # the intent bolt's instruction


def test_bolt_prompt_points_at_prior_approved_files(tmp_path):
    (tmp_path / "01-intent.md").write_text("x")
    (tmp_path / "02-user-stories.md").write_text("y")
    units = next(b for b in E.BOLTS if b.key == "units")
    p = E.bolt_prompt(units, "req", tmp_path)
    assert "01-intent.md" in p and "02-user-stories.md" in p  # read prior


def test_bolt_prompt_regen_flag_asks_for_a_different_draft(tmp_path):
    p = E.bolt_prompt(E.BOLTS[0], "req", tmp_path, regen=True)
    assert "DIFFERENT" in p or "rejected" in p


# ---- validate_artifacts ---------------------------------------------------------

def test_validate_clean_fixture_has_no_warnings():
    assert E.validate_artifacts(FIXTURE) == []


def test_validate_flags_uow_without_posture(tmp_path):
    (tmp_path / "03-units-of-work.md").write_text("- **UoW-1 — a**: a\n- **UoW-2 — b**: b\n")
    (tmp_path / "04-testing-posture.md").write_text("- UoW-1: Given a, When b, Then c.\n")
    w = E.validate_artifacts(tmp_path)
    assert any("UoW-2" in x for x in w) and not any("UoW-1" in x for x in w)


def test_validate_flags_non_gwt_statement(tmp_path):
    (tmp_path / "03-units-of-work.md").write_text("- **UoW-1 — a**: a\n")
    (tmp_path / "04-testing-posture.md").write_text("- UoW-1: it should work.\n")
    assert any("not Given/When/Then" in x for x in E.validate_artifacts(tmp_path))


def test_validate_missing_units_file(tmp_path):
    assert E.validate_artifacts(tmp_path) == ["03-units-of-work.md is missing"]


# ---- run_inception orchestration ------------------------------------------------

def test_run_inception_writes_all_four_contract_files(tmp_path):
    res = E.run_inception("req", tmp_path, approve_fn=_accept, propose_fn=_canned_propose)
    for b in E.BOLTS:
        assert (tmp_path / b.filename).exists()
    assert res["warnings"] == []                      # canned content is compliant
    assert set(res["approved"]) == {"intent", "stories", "units", "posture"}
    assert res["trace_id"].startswith("aidlc-")


def test_run_inception_emits_evidence_trail(tmp_path):
    E.run_inception("req", tmp_path, approve_fn=_accept, propose_fn=_canned_propose)
    trail = (tmp_path / "aidlc_trace.jsonl").read_text().splitlines()
    events = [json.loads(line)["event"] for line in trail]
    assert events[0] == "inception.start"
    assert events.count("inception.bolt") == 4
    assert events[-1] == "inception.ready"
    assert all(json.loads(line)["trace"] == json.loads(trail[0])["trace"] for line in trail)


def test_run_inception_regenerate_reproposes_then_accepts(tmp_path):
    calls = {"intent": 0}

    def propose(bolt, prompt):
        if bolt.key == "intent":
            calls["intent"] += 1
        return CANNED[bolt.key]

    # reject the intent bolt once, then accept everything
    state = {"regened": False}

    def approve(bolt, proposed):
        if bolt.key == "intent" and not state["regened"]:
            state["regened"] = True
            return E.REGENERATE
        return proposed

    E.run_inception("req", tmp_path, approve_fn=approve, propose_fn=propose)
    assert calls["intent"] == 2                        # proposed twice (regenerated once)
    trail = (tmp_path / "aidlc_trace.jsonl").read_text()
    assert "inception.regenerate" in trail


def test_run_inception_surfaces_contract_warnings(tmp_path):
    bad = dict(CANNED, posture="(no posture for UoW-1)\n")

    def propose(bolt, prompt):
        return bad[bolt.key]

    res = E.run_inception("req", tmp_path, approve_fn=_accept, propose_fn=propose)
    assert any("UoW-1" in w for w in res["warnings"])
