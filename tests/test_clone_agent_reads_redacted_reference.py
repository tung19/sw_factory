"""B4 (deep audit 2026-10-28, local-path scope): the RE agent must read a
credential-REDACTED copy of a LOCAL reference, not the byte-exact `_sample/`.

`clone_pipeline` ran the RE agent FIRST (it reads `./_sample`) and screened `_sample/`
only afterward, so a token sitting in the reference reached the agent's context before the
report was even printed. For a local path we now isolate into `_sample/` (byte-exact
evidence), screen+redact it into `_sample_safe/`, and point the agent there. git/URL kinds
still fetch via the agent (closing those needs the pipeline to do the fetch — a funded
live run; tracked as the B4 residual).
"""
import pytest

from area.re import extract as E
from area.spec.models import Acceptance, Spec


class _Stop(Exception):
    pass


def _planted(tmp_path):
    ref = tmp_path / "ref"
    (ref / "lib").mkdir(parents=True)
    (ref / "lib" / "db.ts").write_text('const API_KEY = "sk_live_abcdef0123456789abcd"\n')
    (ref / "app.ts").write_text("export const x = 1\n")
    return ref


def test_local_reference_is_redacted_for_the_agent(tmp_path, monkeypatch):
    ref = _planted(tmp_path)
    out = tmp_path / "specs" / "c"
    monkeypatch.setattr(E, "build_agent", lambda *a, **k: (_ for _ in ()).throw(_Stop()))
    with pytest.raises(_Stop):
        E.spec_from_source(str(ref), out, kind="path")
    sample, safe = out / "_sample", out / "_sample_safe"
    assert "sk_live_abcdef0123456789abcd" in (sample / "lib" / "db.ts").read_text()
    red = (safe / "lib" / "db.ts").read_text()
    assert "sk_live" not in red and "AREA-REDACTED" in red
    assert (safe / "app.ts").read_text() == "export const x = 1\n"


def test_task_points_the_agent_at_the_redacted_copy(tmp_path, monkeypatch):
    ref = _planted(tmp_path)
    out = tmp_path / "specs" / "c"
    seen: dict = {}

    class _A:
        def close(self):
            pass

    monkeypatch.setattr(E, "build_agent", lambda *a, **k: _A())
    monkeypatch.setattr(E, "run_until",
                        lambda agent, ws, task, v, **k: (seen.update(task=task), (True, None))[1])
    monkeypatch.setattr(E, "load_spec", lambda p: Spec(name="c", summary="s"))
    monkeypatch.setattr(E, "load_acceptance", lambda p: Acceptance())
    E.spec_from_source(str(ref), out, kind="path")
    assert "_sample_safe" in seen["task"]
    assert "never fetch over the network" in seen["task"]


def test_strict_refuses_when_the_local_reference_has_a_secret(tmp_path, monkeypatch):
    ref = _planted(tmp_path)
    out = tmp_path / "specs" / "c"
    # build_agent must never be reached — strict refuses before the agent runs
    monkeypatch.setattr(E, "build_agent",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("reached agent")))
    with pytest.raises(RuntimeError, match="strict"):
        E.spec_from_source(str(ref), out, kind="path", strict=True)
