"""The spec had nowhere to record a route map, so clone parity was undetermined.

Found by running Flow B for real. The reverse-engineer stage read `taskboard` well —
it recovered `node:sqlite` with `TASKBOARD_DB`, the `scrypt$<salt>$<hash>` format and
the HMAC `sid` cookie — and recorded **no routes**, because `Spec` had no field for
them. Its own independent reviewer caught the consequence:

> *"What are the actual URLs? No document states the path of the login page, the
> boards-list page, or a board-detail page — yet AC-8 and AC-22 require requesting a
> board URL directly."* → assumed: **"Invent a plausible map."**

Measured: the real routes (`/`, `/login`, `/boards`, `/boards/[id]`) were readable from
`_sample/app/` in a second, and the generated acceptance file quoted **zero** paths.

Why that is an oracle defect and not a documentation gap: `author_until` is handed
`acc_yaml` **alone** and never sees `spec.yaml`. A path absent from the criteria is a
path the holdout author invents — after which the suite is checksum-frozen, the clone
is built to satisfy it, `verify-holdout-intact.sh` reports the oracle intact, and the
whole thing asserts parity against a URL neither app serves.

Same shape as the missing `ui` field that #27/#28 added after "the clone's UI is wrong":
RE was capturing features and the data model, and nothing else had a home.
"""
import pytest

from area.spec.models import (
    Acceptance,
    AcceptanceCriterion,
    Feature,
    Route,
    Spec,
    load_spec,
    routes_unquoted,
    validate_cross,
)


def _spec(routes=(), features=("boards",)):
    return Spec(name="c", summary="s",
                features=[Feature(id=f, title=f, description=f) for f in features],
                routes=[Route(**r) if isinstance(r, dict) else r for r in routes])


def _acc(*whens, feature="boards"):
    return Acceptance(criteria=[
        AcceptanceCriterion(id=f"AC-{i+1}", feature=feature, given="a user",
                            when=w, then="it works")
        for i, w in enumerate(whens)])


def test_a_legacy_spec_still_loads(tmp_path):
    """taskboard, invoice_mgr, fb_incept and expenses all predate this field."""
    p = tmp_path / "spec.yaml"
    p.write_text("name: a\nsummary: s\nfeatures:\n- {id: f, title: t, description: d}\n")
    assert load_spec(p).routes == []


def test_the_exact_failure_is_rejected(tmp_path):
    """A spec whose criteria navigate while declaring no routes — the taskboard clone."""
    problems = validate_cross(
        _spec(routes=()),
        _acc("they request a board URL directly", "they are redirected to the boards page"))
    assert any("spec.routes is empty" in p for p in problems), problems
    assert any("invents the URLs" in p for p in problems)


def test_declaring_the_routes_and_quoting_them_is_accepted():
    spec = _spec(routes=[{"path": "/boards/[id]", "purpose": "a board", "kind": "page"},
                         {"path": "/boards", "purpose": "the list", "kind": "page"}])
    acc = _acc("they request /boards/7 directly", "they are redirected to /boards")
    assert validate_cross(spec, acc) == []
    assert routes_unquoted(spec, acc) == []


def test_a_criterion_that_navigates_without_a_path_is_named(tmp_path):
    """Reported, not fatal: a sibling criterion may pin the path while this one reads as
    prose. Blocking each one would be a false block."""
    spec = _spec(routes=[{"path": "/boards", "purpose": "list", "kind": "page"}])
    acc = _acc("they visit /boards", "they land on the board detail page")
    assert routes_unquoted(spec, acc) == ["AC-2"]
    assert validate_cross(spec, acc) == [], "a single prose criterion must not be fatal"


def test_a_spec_that_never_navigates_needs_no_routes():
    """A library or a pure-logic app has no paths to declare."""
    spec = _spec(routes=())
    acc = _acc("they call add(1050) with an integer number of cents")
    assert routes_unquoted(spec, acc) == []
    assert validate_cross(spec, acc) == []


@pytest.mark.parametrize("bad", ["boards", "boards/[id]", "http://x/boards"])
def test_a_route_must_be_an_absolute_path(bad):
    problems = validate_cross(_spec(routes=[{"path": bad}]), _acc("they do a thing"))
    assert any("not an absolute path" in p for p in problems), problems


@pytest.mark.parametrize("verb", [
    "they visit the login page", "they navigate to the board",
    "they request a board URL", "they are redirected to the list",
    "they land on the boards page", "the page at that url loads",
])
def test_the_navigation_verbs_that_matter_are_detected(verb):
    """If the detector misses a phrasing, the hole comes straight back."""
    assert routes_unquoted(_spec(routes=()), _acc(verb)) == ["AC-1"], verb


def test_the_real_reference_routes_are_what_this_would_have_required():
    """The four paths read out of `_sample/app/` during the live run. Pinned so the
    fixture is the measurement, not an invention."""
    spec = _spec(routes=[{"path": p} for p in
                         ("/", "/login", "/boards", "/boards/[id]")])
    acc = _acc("they request /boards/[id] for a board they do not own",
               "they are redirected to /login")
    assert validate_cross(spec, acc) == []
