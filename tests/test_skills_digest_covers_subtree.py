"""B12 (deep audit 2026-10-28): the per-run skills_digest must cover the whole skill
subtree, not just SKILL.md.

`profile._pack_digest` hashes every file in a pack; `obs.installed_skills` hashed only
each skill's SKILL.md. So two packs sharing skill NAMES but differing in a skill's
`references/*` or vendored scripts (e.g. vinext-cf-build's vendored braces) produced the
SAME run-level skills_digest — and the evals `confounded-skills` guard then could not tell
that two runs actually had different domain knowledge.
"""
from area import obs


def _pack(tmp_path, app, ref_body):
    sk = tmp_path / "apps" / app / ".claude" / "skills" / "s"
    (sk / "references").mkdir(parents=True)
    (sk / "SKILL.md").write_text("---\nname: s\n---\n# identical across packs\n")
    (sk / "references" / "guide.md").write_text(ref_body)


def test_digest_changes_when_a_non_skill_md_file_differs(monkeypatch, tmp_path):
    monkeypatch.setattr(obs, "WORKSPACE", tmp_path)
    monkeypatch.setattr(obs, "_skills_cache", {})
    _pack(tmp_path, "a", "VERSION ONE of the vendored reference")
    _pack(tmp_path, "b", "VERSION TWO of the vendored reference")
    da = obs.installed_skills("a")[0]
    db = obs.installed_skills("b")[0]
    assert da and db and da != db, (
        "two packs with the same SKILL.md but different references collide"
    )


def test_identical_packs_have_the_same_digest(monkeypatch, tmp_path):
    monkeypatch.setattr(obs, "WORKSPACE", tmp_path)
    monkeypatch.setattr(obs, "_skills_cache", {})
    _pack(tmp_path, "a", "same body")
    _pack(tmp_path, "b", "same body")
    assert obs.installed_skills("a")[0] == obs.installed_skills("b")[0]
