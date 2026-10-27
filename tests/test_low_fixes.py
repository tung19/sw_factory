"""Audit LOW-batch fixes: monitor p95 nearest-rank, and the holdout stall-detector
keying on content (not st_size)."""
import json

import area.monitor as M
from area.verify.holdout import _fingerprint


def test_status_p95_is_nearest_rank(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "MONDIR", tmp_path)
    monkeypatch.setattr(M, "deployed_url", lambda n: None)
    log = tmp_path / "app1.jsonl"
    log.write_text("\n".join(json.dumps({"ok": True, "ms": i}) for i in range(1, 11)))
    s = M.status("app1")
    assert s["p95_ms"] == 10          # nearest-rank p95 of 1..10 is the 10th (was 9)


def test_status_p95_single_sample_does_not_wrap(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "MONDIR", tmp_path)
    monkeypatch.setattr(M, "deployed_url", lambda n: None)
    (tmp_path / "a.jsonl").write_text(json.dumps({"ok": True, "ms": 42}))
    assert M.status("a")["p95_ms"] == 42   # not lat[-1] via a negative index by luck


def test_fingerprint_keys_on_content_not_size(tmp_path):
    hd = tmp_path / "__tests__" / "_holdout"
    hd.mkdir(parents=True)
    f = hd / "ac.test.ts"
    f.write_text("AAAA")
    fp1 = _fingerprint(hd)
    f.write_text("BBBB")             # same byte length, different content
    fp2 = _fingerprint(hd)
    assert fp1 != fp2                 # a same-size rewrite now counts as progress
