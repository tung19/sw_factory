"""A locked oracle must never be silently re-authored.

Found by triaging the never-run `holdout-fixer` profile. `author_until` used to call
the author agent unconditionally — and `run_once` fires BEFORE the authoring oracle is
consulted — so `area verify <app>` on a `--tdd`-built app invoked an author agent in a
directory that already held the LOCKED holdout, let it rewrite those files, then
`_persist_lock` rewrote the lock to match. A strong oracle authored pre-build from the
spec ONLY was replaced by one authored post-build against the implementation it could
read, and because the lock was rewritten too, `tools/verify-holdout-intact.sh` then
reported the oracle intact. The tamper detector confirmed independence at the exact
moment independence was lost.

Agent-free: the agent is stubbed, the suite runner is stubbed, nothing is spent.
"""
import subprocess
import types
from pathlib import Path

import pytest

import area.verify.holdout as H

ROOT = Path(__file__).resolve().parents[1]
STRONG = ('// authored pre-build from the spec ONLY\n'
          'import { tip } from "../../lib/tip";\n'
          'describe("AC-1", () => { it("10% of 100 is 10", () => '
          '{ expect(tip(100,10)).toBe(10); }); });\n')
ACC = ("criteria:\n  - {id: AC-1, given: a calculator, when: bill 100 at 10 percent, "
       "then: tip is 10}\n")


def _ws(tmp_path, *, locked: bool, with_source: bool = True) -> Path:
    app = tmp_path / "apps" / "t"
    (app / H.HOLDOUT_DIR).mkdir(parents=True)
    (tmp_path / "specs" / "t").mkdir(parents=True)
    (tmp_path / "specs" / "t" / "acceptance.yaml").write_text(ACC)
    if with_source:
        (app / "lib").mkdir()
        (app / "lib" / "tip.ts").write_text("export const tip=(b,p)=>0;\n")
    (app / H.HOLDOUT_DIR / "ac1.holdout.test.ts").write_text(STRONG)
    if locked:
        subprocess.run(["bash", str(ROOT / "tools" / "lock-holdout.sh"), "t",
                        str(tmp_path)], capture_output=True, text=True, timeout=60)
    return tmp_path


@pytest.fixture
def stub(monkeypatch):
    """Stub the agent and the suite runner; record whether an author was invoked."""
    called: list[str] = []
    monkeypatch.setattr(H, "build_agent",
                        lambda *a, **k: types.SimpleNamespace(close=lambda: None))

    def fake_run_once(agent, app, prompt, label="agent"):
        called.append(label)
        (Path(app) / H.HOLDOUT_DIR / "ac1.holdout.test.ts").write_text(
            'describe("AC-1",()=>{it("mirrors the code",()=>{expect(0).toBe(0);});});')

    monkeypatch.setattr(H, "run_once", fake_run_once)
    monkeypatch.setattr(H, "_authoring_oracle", lambda *a, **k: (True, ""))
    monkeypatch.setattr(H, "_holdout_oracle", lambda app, holdout, lock, **k:
                        (lambda: types.SimpleNamespace(ok=True, feedback="")))
    return called


def test_an_intact_locked_oracle_is_reused_not_re_authored(tmp_path, stub, monkeypatch):
    ws = _ws(tmp_path, locked=True)
    monkeypatch.setattr(H, "WORKSPACE", ws)
    lockfile = ws / "specs" / "t" / "holdout.lock"
    before_lock = lockfile.read_text()
    oracle_file = ws / "apps" / "t" / H.HOLDOUT_DIR / "ac1.holdout.test.ts"

    assert H.holdout_verify("t") is True
    assert stub == [], "no author agent may run against an already-locked oracle"
    assert lockfile.read_text() == before_lock, "the lock was rewritten"
    assert oracle_file.read_text() == STRONG, "the locked oracle was modified"


def test_a_tampered_oracle_is_refused_with_the_challenge_route(tmp_path, stub,
                                                               monkeypatch):
    ws = _ws(tmp_path, locked=True)
    monkeypatch.setattr(H, "WORKSPACE", ws)
    (ws / "apps" / "t" / H.HOLDOUT_DIR / "ac1.holdout.test.ts").write_text(
        'describe("AC-1",()=>{it("weakened",()=>{expect(1).toBe(1);});});')
    with pytest.raises(RuntimeError) as e:
        H.holdout_verify("t")
    msg = str(e.value)
    assert "no longer matches its lock" in msg
    assert H.CHALLENGE_FILE in msg, "must point at the sanctioned re-adjudication route"
    assert stub == []


def test_with_no_lock_it_still_authors(tmp_path, stub, monkeypatch):
    """The genuinely non-TDD path must keep working — this guard only protects an
    EXISTING lock."""
    ws = _ws(tmp_path, locked=False)
    monkeypatch.setattr(H, "WORKSPACE", ws)
    assert H.holdout_verify("t") is True
    assert stub, "with no lock, the author agent must run"


def test_post_build_authoring_is_announced_as_weaker(tmp_path, stub, monkeypatch,
                                                     capsys):
    """CLAUDE.md enforcement (a) is "from the spec ONLY, before any implementation
    exists". The non-TDD gate authors against real modules it can read, so it cannot
    satisfy that — and it has to say so rather than be presented as the same oracle."""
    ws = _ws(tmp_path, locked=False, with_source=True)
    monkeypatch.setattr(H, "WORKSPACE", ws)
    H.holdout_verify("t")
    out = capsys.readouterr().out
    assert "AFTER the implementation exists" in out and "--tdd" in out


def test_no_warning_when_there_is_no_implementation_to_read(tmp_path, stub,
                                                            monkeypatch, capsys):
    ws = _ws(tmp_path, locked=False, with_source=False)
    monkeypatch.setattr(H, "WORKSPACE", ws)
    H.holdout_verify("t")
    assert "AFTER the implementation exists" not in capsys.readouterr().out


def test_locked_state_reports_the_three_cases(tmp_path, monkeypatch):
    ws = _ws(tmp_path, locked=False)
    app = ws / "apps" / "t"
    assert H._locked_state(app) == "none"
    subprocess.run(["bash", str(ROOT / "tools" / "lock-holdout.sh"), "t", str(ws)],
                   capture_output=True, text=True, timeout=60)
    assert H._locked_state(app) == "intact"
    (app / H.HOLDOUT_DIR / "ac1.holdout.test.ts").write_text("// changed\n")
    assert H._locked_state(app) == "tampered"


def test_readjudicate_still_clears_the_lock_first():
    """The ONE sanctioned way to replace a locked oracle must not be blocked by the
    new guard — it clears the lock before re-authoring."""
    import inspect

    src = inspect.getsource(H.readjudicate)
    assert "_clear_lock(app)" in src
    assert src.index("_clear_lock(app)") < src.index("run_once")
