"""B5 (deep audit 2026-10-28): a pre-build skills MISS must not be memoized.

`installed_skills` is memoised per app name for the life of the process. But the app's
`.claude/skills/` is created mid-process (only at the build stage), while the earlier
`spec` stage already calls `installed_skills` — caching `(None, ())`. Every later
build-stage run then reads that stale miss and records `skills: [], skills_digest: null`,
even though the pack IS installed. `area evals` then pairs runs as if they had no domain
knowledge. A miss must re-stat; only a real pack is memoized.
"""
from area import obs


def _install(tmp_path, name, skill="area-oracle-loop"):
    sk = tmp_path / "apps" / name / ".claude" / "skills" / skill
    sk.mkdir(parents=True)
    (sk / "SKILL.md").write_text(f"---\nname: {skill}\n---\n#\n")


def test_a_pre_build_miss_is_not_cached(monkeypatch, tmp_path):
    monkeypatch.setattr(obs, "WORKSPACE", tmp_path)
    monkeypatch.setattr(obs, "_skills_cache", {})
    assert obs.installed_skills("app") == (None, ())   # spec stage: no dir yet
    _install(tmp_path, "app")                           # build stage installs the pack
    digest, names = obs.installed_skills("app")
    assert names == ("area-oracle-loop",) and digest, (
        "the pre-build miss was cached — build-stage runs record a stale (None, ())"
    )


def test_a_real_pack_is_still_memoized(monkeypatch, tmp_path):
    """The perf contract is unchanged: once a real pack is read, it is memoized for the
    process (edits need an explicit cache clear, as the M9 test relies on)."""
    monkeypatch.setattr(obs, "WORKSPACE", tmp_path)
    monkeypatch.setattr(obs, "_skills_cache", {})
    _install(tmp_path, "app")
    first = obs.installed_skills("app")
    assert first[0] is not None
    (tmp_path / "apps" / "app" / ".claude" / "skills" / "area-oracle-loop"
     / "SKILL.md").write_text("changed in-process")
    assert obs.installed_skills("app") == first, "a positive result must stay memoized"
