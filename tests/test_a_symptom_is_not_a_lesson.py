"""The memory store is injected into build prompts, so what it holds must be a lesson.

`run_until` used to call `memory.remember(symptom=first_fail)` on any build that
passed after a retry. The loop knows only what BROKE, never what fixed it, so every
auto-written entry had an empty `fix` — and `as_prompt` renders those as bare bullets
under a header reading "Known pitfalls from past runs (avoid these)", at the very top
of the next build prompt.

What had accumulated in the live store: a `No such file or directory` on a stale path,
raw `npm audit` output truncated mid-table, `No test files found, exiting with code 1`,
and the acceptance oracle's own `FORBIDDEN: files under __tests__/_holdout/ were
modified` rejection — the message that proves the oracle worked, recycled as a pitfall
to avoid.

Harness2 (arXiv:2610.14224) states the rule: keep a lesson only where the evidence
supports it, otherwise add no entry. See docs/harness2-gap-assessment.md F1.
"""
import json

import pytest

from area.engine import VerifyResult
from area.engine import adapter as A
from area.memory import store as M


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A store of our own. (conftest already redirects MEM; this pins it per test.)"""
    monkeypatch.setattr(M, "MEM", tmp_path / "memory.jsonl")
    return M.MEM


def _entries(p):
    if not p.exists():          # nothing written is a legitimate outcome here
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def test_a_symptom_with_no_fix_is_refused(store):
    M.remember(symptom="npm run build exited 1", tags=["build"])
    assert [e for e in _entries(store) if e.get("symptom") == "npm run build exited 1"] == []


def test_a_lesson_with_both_halves_is_stored(store):
    sym = "the dev server binds 3000 and the e2e gate assumes it is free"
    M.remember(symptom=sym, fix="pass a free port into the spec", tags=["build"])
    kept = [e for e in _entries(store) if e["symptom"] == sym]
    assert len(kept) == 1 and kept[0]["fix"].startswith("pass a free port")


def test_the_seeded_lesson_survives_the_guard(store):
    """The seed has both halves, so the guard must not cost us the one real lesson."""
    assert M.lessons(), "the seed did not land"
    assert all(e.get("fix") for e in _entries(store)), "a fix-less entry exists"


def test_the_oracles_own_rejection_can_never_be_stored_as_a_pitfall(store):
    """The exact text that was on disk. It is an enforcement message, not a lesson."""
    M.remember(
        symptom="[build:plain:tdd] FORBIDDEN: files under __tests__/_holdout/ were "
                "modified. Those are the locked acceptance tests — revert them and "
                "fix APP CODE only.",
        tags=["build", "build:plain:tdd"],
    )
    assert not [e for e in _entries(store) if "FORBIDDEN" in e["symptom"]]


def test_a_prompt_built_from_the_store_carries_no_bare_bullet(store):
    M.remember(symptom="symptom only", tags=["build"])
    M.remember(symptom="real one", fix="do the thing", tags=["build"])
    text = M.as_prompt(M.recall(tags=["build"], text="real one thing"))
    assert "symptom only" not in text
    # every bullet that names a symptom must be followed by its FIX line
    bullets = [l for l in text.splitlines() if l.startswith("- ")]
    assert bullets and len(bullets) == text.count("  FIX: ")


def test_a_green_after_retry_build_no_longer_writes_a_symptom_only_entry(store,
                                                                        tmp_path,
                                                                        monkeypatch):
    """The regression test for the actual defect: drive the real `run_until` through
    fail-then-pass, which is exactly the condition that used to write."""
    monkeypatch.setattr(A, "_mk_conversation", lambda *a, **k: object())
    monkeypatch.setattr(A, "_send_and_run", lambda conv, msg: None)
    before = _entries(store) if store.exists() else []

    calls = {"n": 0}

    def verifier():
        calls["n"] += 1
        return VerifyResult(calls["n"] > 1, "npm test exited 1")

    class _Agent:
        def close(self):
            pass

    passed, _ = A.run_until(_Agent(), tmp_path, "task", verifier,
                            max_iters=3, label="build:plain:tdd")
    assert passed is True and calls["n"] > 1, "the fail-then-pass path did not run"
    assert _entries(store) == before, "the retry path wrote to the prompt-fed store"
