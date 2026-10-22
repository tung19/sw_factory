"""area.research — P1 of `area adapt`. The deterministic parts (schema, prompt,
parse, dedup+rank, validate) + the research() orchestration with an INJECTED
runner. No agent / web is touched — the live discovery is dogfooded separately."""
import json

import area.research as R

_BRIEF = {
    "reference": "https://ex/app", "requirement": "a todo app",
    "candidates_considered": 97, "notes": "ok",
    "top": [
        {"repo": "a/one", "url": "https://x/1", "score": 0.9, "features": ["auth"],
         "data_source": "REST", "data_integration": "webhook", "data_storage": "postgres"},
        {"repo": "b/two", "url": "https://x/2", "score": 0.7, "features": ["sync"],
         "data_source": "CSV", "data_integration": "batch", "data_storage": "sqlite"},
    ],
}


# ---- parse_brief --------------------------------------------------------------

def test_parse_brief_clean():
    b = R.parse_brief(json.dumps(_BRIEF))
    assert b.candidates_considered == 97 and len(b.top) == 2
    assert b.top[0].repo == "a/one" and b.top[0].data_storage == "postgres"
    assert b.top[0].score == 0.9 and b.top[0].features == ["auth"]


def test_parse_brief_strips_json_fence():
    fenced = "```json\n" + json.dumps(_BRIEF) + "\n```"
    assert R.parse_brief(fenced).top[1].repo == "b/two"


def test_parse_brief_coerces_missing_fields():
    b = R.parse_brief('{"top": [{"repo": "x/y"}]}')   # minimal repo
    r = b.top[0]
    assert r.url == "" and r.score == 0.0 and r.features == []
    assert r.data_source == "" and b.candidates_considered == 0


def test_parse_brief_rejects_non_object():
    import pytest
    with pytest.raises(ValueError):
        R.parse_brief("[1, 2, 3]")
    with pytest.raises(json.JSONDecodeError):
        R.parse_brief("not json")


# ---- rank_top -----------------------------------------------------------------

def test_rank_top_dedup_sort_and_limit():
    cands = [
        {"repo": "a", "url": "u1", "score": 0.5},
        {"repo": "a2", "url": "u1", "score": 0.8},   # dup url → keep higher score
        {"repo": "b", "url": "u2", "score": 0.9},
        {"repo": "c", "url": "u3", "score": 0.2},
        {"repo": "", "url": "", "score": 1.0},         # no url AND no repo → dropped
    ]
    top = R.rank_top(cands, 2)
    assert [c["url"] for c in top] == ["u2", "u1"]     # 0.9, then deduped-0.8
    assert len(top) == 2


def test_rank_top_keys_by_repo_when_no_url():
    cands = [{"repo": "only-repo", "url": "", "score": 0.3}]
    top = R.rank_top(cands, 5)
    assert len(top) == 1 and top[0]["repo"] == "only-repo"   # repo is a valid key


# ---- validate_brief -----------------------------------------------------------

def test_validate_flags_too_few_and_missing_dims():
    b = R.parse_brief(json.dumps({"top": [
        {"repo": "a/one", "url": "u", "data_source": "x", "data_integration": "y"},
    ]}))  # 1 repo, missing data_storage
    issues = R.validate_brief(b, min_repos=5)
    assert any("only 1" in i for i in issues)
    assert any("data_storage" in i for i in issues)


def test_validate_clean_brief_has_no_issues():
    full = {"top": [
        {"repo": f"r/{i}", "url": f"u{i}", "data_source": "a",
         "data_integration": "b", "data_storage": "c"} for i in range(5)
    ]}
    assert R.validate_brief(R.parse_brief(json.dumps(full)), min_repos=5) == []


# ---- research_prompt ----------------------------------------------------------

def test_prompt_has_key_instructions():
    p = R.research_prompt("https://ex/app", "a todo app", count=100, top=5)
    assert "https://ex/app" in p and "a todo app" in p
    assert "~100" in p and "top 5" in p
    for dim in ("data_source", "data_integration", "data_storage"):
        assert dim in p
    assert R.BRIEF_FILE in p
    assert "DATA" in p and "Do NOT clone" in p   # untrusted-content guard


# ---- research() orchestration (injected runner) -------------------------------

def test_research_reads_brief_from_injected_runner(tmp_path):
    def fake_runner(prompt, ws):
        (ws / R.BRIEF_FILE).write_text(json.dumps(_BRIEF))
    brief = R.research("https://ex/app", "a todo app", workspace=tmp_path,
                       runner=fake_runner)
    assert len(brief.top) == 2 and brief.candidates_considered == 97


def test_research_raises_when_no_brief(tmp_path):
    import pytest
    with pytest.raises(RuntimeError, match="no brief.json"):
        R.research("ref", "req", workspace=tmp_path, runner=lambda p, w: None)
