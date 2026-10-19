"""Clone build-to-parity authoring + the author ORACLE-LOOP that roots out the
wandering-author failure (the bug the live --tdd smoke run surfaced). On the
keyless ACP backend we cannot strip the agent's terminal, so the cure is an
output-quality oracle + re-prompt + no-progress backstop, not tool restriction."""
import types

import pytest

import area.verify.holdout as H

_TWO_AC = (
    "criteria:\n"
    "  - {id: AC-1, feature: f, given: g, when: w, then: t}\n"
    "  - {id: AC-2, feature: f, given: g, when: w, then: t}\n"
)


def _mk_holdout(tmp_path):
    hold = tmp_path / H.HOLDOUT_DIR
    hold.mkdir(parents=True, exist_ok=True)
    return hold


# --- parity prompt + anti-wander ---------------------------------------------

def test_parity_preamble_only_with_reference():
    p = H._author_prompt("criteria: []", tdd=True, reference="https://example.com/app")
    assert "PARITY" in p and "example.com" in p and "_sample" in p
    assert "PARITY" not in H._author_prompt("criteria: []", tdd=True)


def test_tdd_prompt_forbids_wandering():
    p = H._author_prompt("criteria: []", tdd=True)
    assert "EMPTY project directory" in p
    assert "do NOT explore" in p and "do NOT scaffold" in p


# --- the authoring oracle (pure, deterministic) ------------------------------

def test_oracle_passes_a_complete_suite(tmp_path):
    hold = _mk_holdout(tmp_path)
    (hold / "CONTRACT.md").write_text("lib/x: f()\n")
    (hold / "a.test.ts").write_text(
        "describe('AC-1',()=>{it('x',()=>{expect(1).toBe(1)})});"
        "describe('AC-2',()=>{it('y',()=>{expect(2).toBe(2)})})\n"
    )
    ok, fb = H._authoring_oracle(hold, _TWO_AC, require_contract=True)
    assert ok, fb


def test_oracle_flags_uncovered_ac(tmp_path):
    hold = _mk_holdout(tmp_path)
    (hold / "CONTRACT.md").write_text("x")
    (hold / "a.test.ts").write_text("describe('AC-1',()=>{expect(1).toBe(1)})")
    ok, fb = H._authoring_oracle(hold, _TWO_AC, require_contract=True)
    assert not ok and "AC-2" in fb


def test_oracle_flags_no_tests(tmp_path):
    hold = _mk_holdout(tmp_path)
    ok, fb = H._authoring_oracle(hold, "criteria: []", require_contract=False)
    assert not ok and "No Vitest" in fb


def test_oracle_requires_contract_only_in_tdd(tmp_path):
    hold = _mk_holdout(tmp_path)
    one = "criteria:\n  - {id: AC-1, feature: f, given: g, when: w, then: t}\n"
    (hold / "a.test.ts").write_text("describe('AC-1',()=>{expect(1).toBe(1)})")
    ok_tdd, fb = H._authoring_oracle(hold, one, require_contract=True)
    assert not ok_tdd and "CONTRACT.md" in fb
    ok_post, _ = H._authoring_oracle(hold, one, require_contract=False)
    assert ok_post  # post-build gate (app exists) needs no contract file


def test_oracle_flags_missing_assertions(tmp_path):
    hold = _mk_holdout(tmp_path)
    (hold / "CONTRACT.md").write_text("x")
    one = "criteria:\n  - {id: AC-1, feature: f, given: g, when: w, then: t}\n"
    (hold / "a.test.ts").write_text("describe('AC-1',()=>{it('x',()=>{})})")
    ok, fb = H._authoring_oracle(hold, one, require_contract=True)
    assert not ok and "assertion" in fb.lower()


def test_oracle_ac_id_word_boundary(tmp_path):
    # 'AC-1' present must NOT satisfy 'AC-10'
    hold = _mk_holdout(tmp_path)
    (hold / "CONTRACT.md").write_text("x")
    (hold / "a.test.ts").write_text("describe('AC-1',()=>{expect(1).toBe(1)})")
    acc = (
        "criteria:\n"
        "  - {id: AC-1, feature: f, given: g, when: w, then: t}\n"
        "  - {id: AC-10, feature: f, given: g, when: w, then: t}\n"
    )
    ok, fb = H._authoring_oracle(hold, acc, require_contract=True)
    assert not ok and "AC-10" in fb


# --- the author oracle-loop --------------------------------------------------

def test_author_until_reprompts_until_complete(monkeypatch, tmp_path):
    hold = tmp_path / H.HOLDOUT_DIR
    calls = {"n": 0}
    monkeypatch.setattr(H, "build_agent",
                        lambda *a, **k: types.SimpleNamespace(close=lambda: None))

    def fake_run_once(agent, app, prompt, label="x"):
        calls["n"] += 1
        hold.mkdir(parents=True, exist_ok=True)
        (hold / "CONTRACT.md").write_text("lib/x: f()")
        if calls["n"] == 1:  # incomplete: AC-2 missing
            (hold / "a.test.ts").write_text("describe('AC-1',()=>{expect(1).toBe(1)})")
        else:                # complete
            (hold / "a.test.ts").write_text(
                "describe('AC-1',()=>{expect(1).toBe(1)});"
                "describe('AC-2',()=>{expect(2).toBe(2)})"
            )

    monkeypatch.setattr(H, "run_once", fake_run_once)
    holdout, lock = H.author_until(tmp_path, _TWO_AC, backend="acp", model=None, tdd=True)
    assert calls["n"] == 2 and "a.test.ts" in lock and "CONTRACT.md" in lock


def test_author_until_stops_on_no_progress(monkeypatch, tmp_path):
    hold = tmp_path / H.HOLDOUT_DIR
    monkeypatch.setattr(H, "build_agent",
                        lambda *a, **k: types.SimpleNamespace(close=lambda: None))

    def stuck(agent, app, prompt, label="x"):  # always the same incomplete output
        hold.mkdir(parents=True, exist_ok=True)
        (hold / "CONTRACT.md").write_text("x")
        (hold / "a.test.ts").write_text("describe('AC-1',()=>{expect(1).toBe(1)})")

    monkeypatch.setattr(H, "run_once", stuck)
    with pytest.raises(RuntimeError) as e:
        H.author_until(tmp_path, _TWO_AC, backend="acp", model=None, tdd=True,
                       attempts=6, max_no_progress=2)
    assert "no progress" in str(e.value)


def test_author_until_raises_when_nothing_written(monkeypatch, tmp_path):
    monkeypatch.setattr(H, "build_agent",
                        lambda *a, **k: types.SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(H, "run_once", lambda *a, **k: None)  # pure wander, no files
    with pytest.raises(RuntimeError):
        H.author_until(tmp_path, _TWO_AC, backend="acp", model=None, tdd=True, attempts=3)
