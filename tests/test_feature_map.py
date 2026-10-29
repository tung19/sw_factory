"""area.feature_map — the condensed "what does this app do and how do I reach it" map,
rendered from spec.yaml + acceptance.yaml and refreshed on every build/iterate.

Pure logic — no agents. Also pins the ONE wiring point (`_build`, shared by all four
pipelines) so the map is never silently absent on clone/intake/iterate — the
'capability threaded through one entrypoint' trap.
"""
import area.feature_map as FM
import area.pipeline as P
from area.spec.models import Acceptance, AcceptanceCriterion, Entity, EntityField, Feature, Route, Spec


def _spec():
    return Spec(
        name="shop", summary="a tiny shop", stack="nextjs",
        entities=[Entity(name="Item", fields=[
            EntityField(name="id", type="int", required=True),
            EntityField(name="name", type="string", required=True)])],
        features=[
            Feature(id="browse", title="Browse items", description="see the catalog"),
            Feature(id="checkout", title="Checkout", description="pay for a cart")],
        routes=[Route(path="/", purpose="catalog", kind="page"),
                Route(path="/cart", purpose="the cart", kind="page")])


def _acc():
    return Acceptance(criteria=[
        AcceptanceCriterion(id="AC-1", feature="browse", given="items exist",
                            when="they open /", then="the catalog lists items",
                            verify_by="execution"),
        AcceptanceCriterion(id="AC-2", feature="checkout", given="a cart with items",
                            when="they submit payment on /cart",
                            then="an order is created", verify_by="execution")])


def test_render_lists_every_feature_route_and_ac():
    md = FM.render(_spec(), _acc())
    assert "Feature map — shop" in md
    for token in ("browse", "checkout", "Browse items", "Checkout",
                  "AC-1", "AC-2", "/cart", "Item"):
        assert token in md, token


def test_render_maps_each_ac_to_the_route_it_reaches():
    md = FM.render(_spec(), _acc())
    # AC-2 mentions /cart in its `when`; the Reaches column should name it.
    row = [ln for ln in md.splitlines() if ln.startswith("| AC-2 ")][0]
    assert "`/cart`" in row


def test_render_handles_a_routeless_spec():
    s = _spec()
    s.routes = []
    md = FM.render(s, _acc())
    assert "_No routes declared._" in md


def test_write_creates_the_file_under_specs_dir(tmp_path):
    out = FM.write_feature_map(_spec(), _acc(), tmp_path / "specs" / "shop")
    assert out.name == "FEATURE_MAP.md"
    assert out.exists() and "Feature map — shop" in out.read_text()


def test_build_emits_the_map_for_every_pipeline(monkeypatch, tmp_path):
    # _build is the single convergence point of run/iterate/intake/clone. Prove the
    # map lands there (and that a non-green build still gets one — it is spec-derived).
    monkeypatch.setattr(P, "build_app", lambda *a, **k: False)   # no agent, NOT green
    res = P._build("shop", _spec(), _acc(), tmp_path, "plain", "acp", None, 1)
    fm = tmp_path / "specs" / "shop" / "FEATURE_MAP.md"
    assert fm.exists(), "FEATURE_MAP.md must be emitted from the shared _build step"
    assert res.passed is False and "browse" in fm.read_text()


def test_cli_exposes_feature_map(tmp_path):
    from area.cli import _build_parser

    ns = _build_parser().parse_args(["feature-map", "shop"])
    assert ns.cmd == "feature-map" and ns.name == "shop"
