"""B9 (deep audit 2026-10-28): the agent's `.area-lesson.md` must never reach the
attested artifact digest, and must not survive a build that didn't harvest it.

`_harvest_lesson` deletes the file, but it runs only on a failed-then-passed build
(`passed and used > 1 and first_fail`). A failed build, or a first-try-green rebuild,
left any lesson file the agent wrote during retries in the app dir — and `.md` is not in
provenance's skip set, so `artifact_digest` hashed it into the attested product,
contradicting both docstrings' "never reaches the artifact digest / deleted either way".
"""
import types

import area.engine.adapter as A
import area.provenance as P
from area.memory import LESSON_FILE


def test_lesson_file_is_excluded_from_the_artifact_digest(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "index.ts").write_text("export const x = 1\n")
    before = P.artifact_digest(app)
    (app / LESSON_FILE).write_text("SYMPTOM: a\nFIX: b\n")
    assert P.artifact_digest(app) == before, "the lesson file leaked into the digest"


def test_a_failed_build_does_not_leave_the_lesson_file(tmp_path, monkeypatch):
    (tmp_path / LESSON_FILE).write_text("SYMPTOM: x\n")   # the agent wrote it mid-run
    monkeypatch.setattr(A, "_mk_conversation", lambda *a, **k: object())
    monkeypatch.setattr(A, "_send_and_run", lambda *a, **k: None)
    fail = types.SimpleNamespace(ok=False, feedback="nope")
    passed, _ = A.run_until(object(), tmp_path, "task", lambda: fail,
                            max_iters=1, label="builder")
    assert passed is False
    assert not (tmp_path / LESSON_FILE).exists(), "a failed build left the lesson file"
