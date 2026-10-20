"""area.verify.holdout on-disk lock persistence. A --tdd build keeps its holdout
checksum in memory; these helpers also write workspace/specs/<name>/holdout.lock
(via the canonical tools/lock-holdout.sh) so tools/verify-holdout-intact.sh AND
the PreToolUse guard hook recognize a --tdd-locked holdout, not only a hand-locked
one. The agent-driven author/readjudicate flows are NOT run here."""
import subprocess

import area.verify.holdout as H


def _mk_holdout(ws, name="app1"):
    app = ws / "apps" / name
    hold = app / H.HOLDOUT_DIR
    hold.mkdir(parents=True)
    (hold / "ac.holdout.test.ts").write_text("import {expect,test} from 'vitest'\n")
    (hold / "CONTRACT.md").write_text("# contract\n")
    return app


def test_lock_file_standard_layout(tmp_path):
    app = tmp_path / "apps" / "app1"
    lf = H._lock_file(app)
    assert lf == tmp_path / "specs" / "app1" / "holdout.lock"


def test_lock_file_non_standard_layout_is_none(tmp_path):
    assert H._lock_file(tmp_path / "somewhere" / "app1") is None   # parent != 'apps'


def test_persist_lock_writes_a_lock_the_shell_verifier_accepts(tmp_path):
    app = _mk_holdout(tmp_path, "app1")
    H._persist_lock(app)
    lock = tmp_path / "specs" / "app1" / "holdout.lock"
    assert lock.exists() and lock.read_text().strip()      # non-empty

    # The canonical shell verifier must accept exactly what _persist_lock wrote.
    script = H.Path(H.__file__).resolve().parents[2] / "tools" / "verify-holdout-intact.sh"
    r = subprocess.run(["bash", str(script), "app1", str(tmp_path)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr          # intact


def test_persist_lock_skips_non_standard_layout(tmp_path):
    odd = tmp_path / "somewhere" / "app1"
    (odd / H.HOLDOUT_DIR).mkdir(parents=True)
    H._persist_lock(odd)                                   # no 'apps' parent → no-op
    assert not (tmp_path / "specs").exists()


def test_clear_lock_removes_then_is_noop(tmp_path):
    app = _mk_holdout(tmp_path, "app1")
    H._persist_lock(app)
    lock = tmp_path / "specs" / "app1" / "holdout.lock"
    assert lock.exists()
    H._clear_lock(app)
    assert not lock.exists()
    H._clear_lock(app)                                     # absent → no error
