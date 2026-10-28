"""area.adapt — P2 of `area adapt`: requirement-anchored synthesis + provenance +
one-shot clarify payload. Pure logic (agent-free)."""
import area.adapt as AD
from area.research import RepoAnalysis, ResearchBrief
from area.spec.models import AcceptanceCriterion, Feature


def _f(fid, title="t", desc="d"):
    return Feature(id=fid, title=title, description=desc)


def _brief(*repos):
    return ResearchBrief(reference="r", requirement="q", candidates_considered=50,
                         top=list(repos))


# ---- merge_by_source (generic, priority-wins) ---------------------------------

def test_merge_priority_wins_and_provenance():
    merged, prov = AD.merge_by_source([
        ("requirement", [_f("a"), _f("b")]),
        ("reference", [_f("b"), _f("c")]),   # b duplicate → requirement keeps it
        ("research", [_f("d")]),
    ])
    assert [f.id for f in merged] == ["a", "b", "c", "d"]
    assert prov == {"a": "requirement", "b": "requirement", "c": "reference", "d": "research"}


def test_merge_requirement_wins_on_conflict():
    # AC-2: same id in requirement AND reference with different content → requirement
    merged, prov = AD.merge_by_source([
        ("requirement", [_f("x", title="REQ version")]),
        ("reference", [_f("x", title="REF version")]),
    ])
    assert len(merged) == 1
    assert merged[0].title == "REQ version" and prov["x"] == "requirement"


def test_merge_is_generic_over_acceptance():
    ac = lambda i, f: AcceptanceCriterion(id=i, feature=f, given="g", when="w", then="t")
    merged, prov = AD.merge_by_source([
        ("requirement", [ac("AC-1", "a")]),
        ("research", [ac("AC-1", "z"), ac("AC-2", "b")]),
    ])
    assert [c.id for c in merged] == ["AC-1", "AC-2"]
    assert merged[0].feature == "a"          # requirement's AC-1 kept
    assert prov == {"AC-1": "requirement", "AC-2": "research"}


# ---- features_from_brief ------------------------------------------------------

def test_features_from_brief_dedup_by_slug():
    b = _brief(
        RepoAnalysis(repo="a/one", url="u1", features=["Add todo", "Dark mode"]),
        RepoAnalysis(repo="b/two", url="u2", features=["add-todo", "Sync"]),  # dup slug
    )
    feats = AD.features_from_brief(b)
    ids = sorted(f.id for f in feats)
    assert ids == ["add-todo", "dark-mode", "sync"]
    addtodo = next(f for f in feats if f.id == "add-todo")
    assert "a/one" in addtodo.description and "b/two" in addtodo.description


# ---- synthesize_features (requirement-anchored) -------------------------------

def test_synthesize_requirement_anchored_fills_gaps():
    req = [_f("checkout")]
    ref = [_f("cart"), _f("checkout", title="ref-checkout")]  # checkout conflict
    brief = _brief(RepoAnalysis(repo="x/y", url="u", features=["Wishlist"]))
    feats, prov = AD.synthesize_features(req, ref, brief)
    ids = [f.id for f in feats]
    assert ids == ["checkout", "cart", "wishlist"]            # req first, then ref, then research
    assert next(f for f in feats if f.id == "checkout").title == "t"  # REQ version kept
    assert prov == {"checkout": "requirement", "cart": "reference", "wishlist": "research"}


# ---- clarify payload / auto_filled --------------------------------------------

def test_auto_filled_and_clarify_payload():
    prov = {"checkout": "requirement", "cart": "reference", "wishlist": "research"}
    assert sorted(AD.auto_filled(prov)) == ["cart", "wishlist"]   # non-requirement
    payload = {p["id"]: p for p in AD.clarify_payload(prov)}
    assert payload["checkout"]["auto_filled"] is False
    assert payload["cart"]["auto_filled"] is True
    assert payload["wishlist"]["source"] == "research"


# ---- P3: the data dimension ---------------------------------------------------

def _rb(*storages):
    return _brief(*[RepoAnalysis(repo=f"r/{i}", url=f"u{i}", data_storage=s,
                                 data_integration="batch ETL", data_source="CSV upload")
                    for i, s in enumerate(storages)])


def test_data_plan_majority_vote():
    plan = AD.synthesize_data_plan(_rb("postgres", "sqlite", "postgres"))
    assert plan.storage == "postgres"          # 2x postgres beats 1x sqlite
    assert plan.integration == "batch ETL" and plan.source == "CSV upload"


def test_data_plan_requirement_override_wins():
    plan = AD.synthesize_data_plan(_rb("postgres", "postgres"), storage="D1",
                                   source="user input")
    assert plan.storage == "D1"                 # override beats the majority
    assert plan.source == "user input"
    assert plan.integration == "batch ETL"      # not overridden → majority


def test_data_plan_empty_brief_defaults():
    plan = AD.synthesize_data_plan(_brief())
    assert plan.storage == "sqlite/D1" and plan.integration == "none"
    assert plan.source == "user input"


def test_data_acceptance_persistence_and_ingest():
    plan = AD.DataPlan(storage="postgres", integration="batch ETL", source="CSV")
    acs = AD.data_acceptance(plan, start_index=5)
    assert [a.id for a in acs] == ["AC-5", "AC-6"]
    assert acs[0].feature == "data-persistence" and "postgres" in acs[0].then
    assert acs[1].feature == "data-ingest" and "CSV" in acs[1].given


def test_data_acceptance_no_ingest_when_integration_none():
    plan = AD.DataPlan(storage="sqlite/D1", integration="none", source="user input")
    acs = AD.data_acceptance(plan)
    assert [a.id for a in acs] == ["AC-5"]      # persistence only, no ingest AC


def test_data_build_notes_mentions_storage_ingest_entities():
    plan = AD.DataPlan(storage="postgres", integration="webhook", source="REST API",
                       entities=["user", "order"])
    notes = AD.data_build_notes(plan)
    assert "postgres" in notes and "restart" in notes
    assert "webhook" in notes and "REST API" in notes
    assert "user, order" in notes
    # no ingest sentence when integration is none
    plain = AD.data_build_notes(AD.DataPlan(storage="sqlite/D1", integration="none", source="x"))
    assert "ingest" not in plain.lower()


# ---- capstone: adapt_pipeline -------------------------------------------------

import json as _json


def _researcher(brief_dict):
    def run(prompt, ws):
        (ws / "brief.json").write_text(_json.dumps(brief_dict))
    return run


_BRIEF_D = {
    "reference": "https://ref", "requirement": "build X", "candidates_considered": 80,
    "top": [{"repo": "a/b", "url": "u", "features": ["Full text search"],
             "data_source": "REST", "data_integration": "webhook",
             "data_storage": "postgres"}],
}


def test_adapt_compose_writes_spec_when_accepted(tmp_path):
    res = AD.adapt_pipeline(
        "https://ref", "build X", name="app1",
        requirement_features=[_f("login", "Login")],
        reference_features=[_f("dashboard", "Dashboard")],
        researcher=_researcher(_BRIEF_D), clarify=False, workspace=tmp_path)
    assert res.clarify_needed is False
    ids = [f.id for f in res.spec.features]
    assert "login" in ids and res.provenance["login"] == "requirement"
    assert res.data_plan.storage == "postgres"       # from the brief
    sd = tmp_path / "specs" / "app1"
    assert (sd / "spec.yaml").exists() and (sd / "acceptance.yaml").exists()
    assert any(c.feature == "data-persistence" for c in res.acceptance.criteria)


def test_adapt_clarify_stops_when_requirement_silent(tmp_path):
    # no requirement features → everything auto-filled from reference/research → STOP
    res = AD.adapt_pipeline(
        "https://ref", "build X", name="app2",
        requirement_features=[], reference_features=[_f("dashboard")],
        researcher=_researcher(_BRIEF_D), clarify=True, workspace=tmp_path)
    assert res.clarify_needed is True
    assert not (tmp_path / "specs" / "app2" / "spec.yaml").exists()   # not written


def test_adapt_confirm_proceeds(tmp_path):
    res = AD.adapt_pipeline(
        "https://ref", "build X", name="app3",
        requirement_features=[], reference_features=[_f("dashboard")],
        researcher=_researcher(_BRIEF_D), clarify=True,
        confirm=lambda r: True, workspace=tmp_path)
    assert res.clarify_needed is False
    assert (tmp_path / "specs" / "app3" / "spec.yaml").exists()


def test_adapt_no_clarify_when_fully_requirement(tmp_path):
    empty_brief = {**_BRIEF_D, "top": [{"repo": "a/b", "url": "u", "features": [],
                   "data_source": "", "data_integration": "", "data_storage": ""}]}
    res = AD.adapt_pipeline(
        "https://ref", "build X", name="app4",
        requirement_features=[_f("login")], reference_features=[],
        researcher=_researcher(empty_brief), clarify=True, workspace=tmp_path)
    assert res.clarify_needed is False   # nothing auto-filled → no stop
    assert (tmp_path / "specs" / "app4" / "spec.yaml").exists()


def test_adapt_seed_opt_in(tmp_path):
    from area.seed import SeedPolicy
    recs = [{"id": 1, "email": "a@b.c", "title": "t"}]
    res = AD.adapt_pipeline(
        "https://ref", "build X", name="app5", requirement_features=[_f("x")],
        reference_features=[], researcher=_researcher(_BRIEF_D), clarify=False,
        seed_policy=SeedPolicy(), seed_records=recs, workspace=tmp_path)
    assert res.seed is not None and res.seed.ok and res.seed.seeded == 1
    assert res.seed.records[0] == {"id": 1, "title": "t"}   # PII stripped

    # The authorization attestation gate was removed — seeding (opt-in via a passed
    # seed_policy) proceeds on the remaining safeguards without an attestation flag.
    res2 = AD.adapt_pipeline(
        "https://ref", "build X", name="app6", requirement_features=[_f("x")],
        reference_features=[], researcher=_researcher(_BRIEF_D), clarify=False,
        seed_policy=SeedPolicy(), seed_records=recs, workspace=tmp_path)
    assert res2.seed is not None and res2.seed.ok and res2.seed.seeded == 1
