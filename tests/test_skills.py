"""area.skills — ship AREA's skill pack into an app dir so the ACP Claude Code
agent discovers them (project .claude/skills, loaded by cwd — verified live)."""
import area.skills as S


def _fake_pack(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    for n in ("area-oracle-loop", "vinext-cf-build", "junk-no-skillmd"):
        d = tmp_path / n
        d.mkdir()
        if n != "junk-no-skillmd":
            (d / "SKILL.md").write_text(f"---\nname: {n}\n---\nbody")
    return tmp_path


def test_skill_names_needs_skillmd(tmp_path):
    src = _fake_pack(tmp_path)
    assert S.skill_names(src) == ["area-oracle-loop", "vinext-cf-build"]  # junk excluded


def test_install_copies_into_dot_claude_skills(tmp_path):
    src = _fake_pack(tmp_path / "src")
    app = tmp_path / "app"
    app.mkdir()
    installed = S.install_skills(app, src=src)
    assert installed == ["area-oracle-loop", "vinext-cf-build"]
    assert (app / ".claude" / "skills" / "area-oracle-loop" / "SKILL.md").exists()
    assert (app / ".claude" / "skills" / "vinext-cf-build" / "SKILL.md").exists()


def test_install_idempotent(tmp_path):
    src = _fake_pack(tmp_path / "src")
    app = tmp_path / "app"
    S.install_skills(app, src=src)
    assert S.install_skills(app, src=src) == ["area-oracle-loop", "vinext-cf-build"]


def test_repo_ships_the_two_skills():
    # the real repo pack
    names = S.skill_names()
    assert "area-oracle-loop" in names and "vinext-cf-build" in names


def test_preamble_mentions_oracle_and_is_target_aware():
    cf = S.skills_preamble("cloudflare")
    assert "/area-oracle-loop" in cf and "/vinext-cf-build" in cf
    plain = S.skills_preamble("plain")
    assert "/area-oracle-loop" in plain and "/vinext-cf-build" not in plain
