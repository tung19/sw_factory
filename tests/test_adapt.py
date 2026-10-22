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
