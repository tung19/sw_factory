"""area.seed — P4 of `area adapt`: opt-in seed-from-reference safeguards. Pure logic
(the fetch is upstream/agent) — robots.txt, PII stripping, cap."""
import area.seed as S


# ---- PII stripping + record cap -----------------------------------------------

def test_seed_strips_pii_by_default():
    recs = [{"id": 1, "title": "x", "email": "a@b.c", "name": "Bob"}]
    r = S.seed_from_reference("ref", recs, S.SeedPolicy())
    assert r.ok and r.seeded == 1
    assert r.records[0] == {"id": 1, "title": "x"}      # email + name dropped
    assert r.skipped_pii_fields == 2


def test_seed_keeps_pii_when_opted_in():
    recs = [{"id": 1, "email": "a@b.c"}]
    r = S.seed_from_reference("ref", recs, S.SeedPolicy(include_pii=True))
    assert r.records[0] == {"id": 1, "email": "a@b.c"} and r.skipped_pii_fields == 0


def test_seed_caps_record_count():
    recs = [{"id": i} for i in range(50)]
    r = S.seed_from_reference("ref", recs, S.SeedPolicy(max_records=10))
    assert r.seeded == 10


def test_is_pii_field_and_strip():
    assert S.is_pii_field("Email") and S.is_pii_field("first_name")
    assert not S.is_pii_field("title")
    clean, dropped = S.strip_pii({"title": "t", "ssn": "x", "phone": "y"})
    assert clean == {"title": "t"} and dropped == 2


# ---- robots.txt ---------------------------------------------------------------

_ROBOTS = "User-agent: *\nDisallow: /private\nAllow: /private/ok\n"


def test_robots_disallows_matching_prefix():
    assert S.robots_allows(_ROBOTS, "/public") is True
    assert S.robots_allows(_ROBOTS, "/private/secret") is False
    assert S.robots_allows(_ROBOTS, "/private/ok/1") is True   # longer Allow wins


def test_robots_empty_disallow_allows_all():
    assert S.robots_allows("User-agent: *\nDisallow:\n", "/anything") is True


def test_robots_specific_user_agent_group():
    robots = ("User-agent: *\nDisallow:\n"
              "User-agent: area-adapt-seed\nDisallow: /\n")
    # the named group (Disallow: /) applies to our UA, not the permissive *
    assert S.robots_allows(robots, "/x", user_agent="area-adapt-seed") is False
    assert S.robots_allows(robots, "/x", user_agent="other-bot") is True


def test_seed_blocked_by_robots():
    r = S.seed_from_reference("ref", [{"id": 1}], S.SeedPolicy(),
                              robots_txt="User-agent: *\nDisallow: /\n", path="/data")
    assert r.ok is False and "robots.txt" in r.blocked_reason


def test_seed_proceeds_without_attestation():
    """The authorization attestation gate was removed by request — seeding runs on the
    remaining safeguards (robots/PII/cap) without a separate 'I have the right' step."""
    r = S.seed_from_reference("https://ref", [{"id": 1, "title": "x"}], S.SeedPolicy())
    assert r.ok and r.seeded == 1 and r.records[0] == {"id": 1, "title": "x"}
