"""TDD pipeline ordering + the governed challenge loop, with every agent-driven
step stubbed. Asserts: tests are locked BEFORE the build; non-TDD never authors;
a valid challenge triggers exactly one bounded rebuild; a rejected challenge
stops; and max_challenges bounds the rebuilds."""
import types

import area.pipeline
import area.verify.holdout as H


def _spec_acc():
    return (
        types.SimpleNamespace(features=[], model_dump=lambda: {"s": 1}),
        types.SimpleNamespace(criteria=[], model_dump=lambda: {"a": 1}),
    )


def test_tdd_locks_before_build(monkeypatch, tmp_path):
    order = []
    monkeypatch.setattr(H, "author_and_lock",
                        lambda *a, **k: (order.append("lock"), (tmp_path / "h", {}))[1])
    monkeypatch.setattr(H, "tdd_build_oracle", lambda *a, **k: (lambda: None))
    monkeypatch.setattr(area.pipeline, "build_app",
                        lambda *a, **k: (order.append("build"), True)[1])
    spec, acc = _spec_acc()
    res = area.pipeline._build("app", spec, acc, tmp_path, "plain", "acp", None, 3, tdd=True)
    assert res.passed and order == ["lock", "build"]


def test_non_tdd_never_authors(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise AssertionError("must not author holdout in non-tdd build")

    monkeypatch.setattr(H, "author_and_lock", boom)
    monkeypatch.setattr(area.pipeline, "build_app", lambda *a, **k: True)
    spec, acc = _spec_acc()
    res = area.pipeline._build("app", spec, acc, tmp_path, "plain", "acp", None, 3, tdd=False)
    assert res.passed


def test_valid_challenge_triggers_one_rebuild(monkeypatch, tmp_path):
    builds = []
    monkeypatch.setattr(H, "author_and_lock", lambda *a, **k: (tmp_path / "h", {"t": "v0"}))
    monkeypatch.setattr(H, "tdd_build_oracle", lambda *a, **k: (lambda: None))
    monkeypatch.setattr(H, "readjudicate", lambda *a, **k: (True, {"t": "v1"}))
    monkeypatch.setattr(area.pipeline, "build_app",
                        lambda *a, **k: (builds.append(1), len(builds) >= 2)[1])
    spec, acc = _spec_acc()
    res = area.pipeline._build("app", spec, acc, tmp_path, "plain", "acp", None, 3, tdd=True)
    assert res.passed and len(builds) == 2


def test_rejected_challenge_stops_without_rebuild(monkeypatch, tmp_path):
    builds = []
    monkeypatch.setattr(H, "author_and_lock", lambda *a, **k: (tmp_path / "h", {"t": "v0"}))
    monkeypatch.setattr(H, "tdd_build_oracle", lambda *a, **k: (lambda: None))
    monkeypatch.setattr(H, "readjudicate", lambda *a, **k: (False, {"t": "v0"}))
    monkeypatch.setattr(area.pipeline, "build_app",
                        lambda *a, **k: (builds.append(1), False)[1])
    spec, acc = _spec_acc()
    res = area.pipeline._build("app", spec, acc, tmp_path, "plain", "acp", None, 3, tdd=True)
    assert not res.passed and len(builds) == 1


def test_max_challenges_bounds_rebuilds(monkeypatch, tmp_path):
    builds = []
    monkeypatch.setattr(H, "author_and_lock", lambda *a, **k: (tmp_path / "h", {"t": 0}))
    monkeypatch.setattr(H, "tdd_build_oracle", lambda *a, **k: (lambda: None))
    monkeypatch.setattr(H, "readjudicate", lambda *a, **k: (True, {"t": 1}))
    monkeypatch.setattr(area.pipeline, "build_app",
                        lambda *a, **k: (builds.append(1), False)[1])
    spec, acc = _spec_acc()
    ok = area.pipeline._tdd_build(
        "app", spec, acc, tmp_path / "apps" / "app", "plain", "acp", None, 3, "",
        max_challenges=2,
    )
    assert not ok and len(builds) == 3  # initial + 2 bounded rebuilds
