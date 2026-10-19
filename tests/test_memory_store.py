"""The experience store (lesson -> recall) that feeds pitfalls back into build
prompts. Pure, file-based; we redirect MEM to a temp file so the real store is
never touched."""
import area.memory.store as store


def _use_tmp(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "MEM", tmp_path / "memory.jsonl")


def test_seeds_on_first_use(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    ls = store.lessons()
    assert any("vinext" in e.get("symptom", "") for e in ls)  # seeded gotcha


def test_remember_then_recall_by_tag(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    store.remember("widget frobnicator explodes on empty input", fix="guard None",
                   tags=["build", "frob"])
    hits = store.recall(tags=["frob"])
    assert hits and "frobnicator" in hits[0]["symptom"]


def test_remember_dedupes_identical(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    for _ in range(3):
        store.remember("same symptom", tags=["t"])
    same = [e for e in store.lessons() if e.get("symptom") == "same symptom"]
    assert len(same) == 1


def test_empty_symptom_is_ignored(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    before = len(store.lessons())
    store.remember("   ", tags=["t"])
    assert len(store.lessons()) == before


def test_recall_by_text_overlap(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    store.remember("compat-date must not exceed workerd release", tags=["cf"])
    hits = store.recall(text="our build broke on compat-date again")
    assert any("compat-date" in e["symptom"] for e in hits)


def test_as_prompt_formats_or_empties():
    assert store.as_prompt([]) == ""
    out = store.as_prompt([{"symptom": "boom", "fix": "patch"}])
    assert "boom" in out and "FIX: patch" in out
