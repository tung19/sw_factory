"""The anti-self-certification core: a built app's acceptance tests are locked
and the implementer cannot weaken them. This is the guarantee the whole "done"
claim rests on, so it is tested directly."""
from pathlib import Path

from area.verify.holdout import (
    CHALLENGE_FILE,
    HOLDOUT_DIR,
    _holdout_oracle,
    _lock,
    pending_challenge,
    tdd_build_oracle,
)


def _mk(tmp_path) -> Path:
    hold = tmp_path / HOLDOUT_DIR
    hold.mkdir(parents=True)
    (hold / "ac1.test.ts").write_text("describe('AC-1', () => {})\n")
    (hold / "CONTRACT.md").write_text("lib/todo.ts: addTodo(x)\n")
    return hold


def test_lock_covers_tests_but_excludes_challenge(tmp_path):
    hold = _mk(tmp_path)
    (hold / CHALLENGE_FILE).write_text("some challenge\n")
    lock = _lock(hold)
    assert set(lock) == {"ac1.test.ts", "CONTRACT.md"}  # challenge NOT locked


def test_clean_suite_passes(tmp_path):
    hold = _mk(tmp_path)
    oracle = _holdout_oracle(tmp_path, hold, _lock(hold), cmd=["bash", "-lc", "exit 0"])
    assert oracle().ok


def test_weakening_a_locked_test_is_forbidden(tmp_path):
    hold = _mk(tmp_path)
    oracle = _holdout_oracle(tmp_path, hold, _lock(hold), cmd=["bash", "-lc", "exit 0"])
    (hold / "ac1.test.ts").write_text("describe('AC-1', () => { it.skip('x', () => {}) })\n")
    r = oracle()
    assert not r.ok and "FORBIDDEN" in r.feedback


def test_deleting_a_locked_test_is_forbidden(tmp_path):
    hold = _mk(tmp_path)
    oracle = _holdout_oracle(tmp_path, hold, _lock(hold), cmd=["bash", "-lc", "exit 0"])
    (hold / "ac1.test.ts").unlink()
    assert not oracle().ok


def test_failing_tests_fail_the_oracle_even_when_untouched(tmp_path):
    hold = _mk(tmp_path)
    oracle = _holdout_oracle(tmp_path, hold, _lock(hold), cmd=["bash", "-lc", "exit 1"])
    r = oracle()
    assert not r.ok and "FORBIDDEN" not in r.feedback  # a real test failure, not tampering


def test_raising_a_challenge_is_not_tampering(tmp_path):
    hold = _mk(tmp_path)
    oracle = _holdout_oracle(tmp_path, hold, _lock(hold), cmd=["bash", "-lc", "exit 0"])
    (hold / CHALLENGE_FILE).write_text("ac1 contradicts the spec — impossible.\n")
    assert oracle().ok                      # sanctioned signal, lock still holds
    assert pending_challenge(hold)          # and it is seen as pending


def test_rejected_challenge_is_resolved(tmp_path):
    hold = _mk(tmp_path)
    (hold / CHALLENGE_FILE).write_text("REJECTED: the spec clearly requires it.\n")
    assert pending_challenge(hold) is None


def test_tdd_build_oracle_composes_build_and_holdout(tmp_path):
    hold = _mk(tmp_path)
    for target, token in (("cloudflare", "build:cf"), ("plain", "build")):
        oracle = tdd_build_oracle(tmp_path, hold, _lock(hold), target=target)
        cmd = next(
            c.cell_contents
            for c in oracle.__closure__
            if isinstance(getattr(c, "cell_contents", None), list)
        )
        assert token in cmd[-1] and HOLDOUT_DIR in cmd[-1]
