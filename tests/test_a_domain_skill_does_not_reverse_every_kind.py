"""A Cloudflare skill must not re-version the kinds a Cloudflare build never involves.

Measured before this change: editing ONLY `skills/vinext-cf-build/SKILL.md` moved the
digest of 7 of 16 kinds — exactly the set declaring `skills: all` or `inherited`, so it
moved `e2e-author`, `chaos-author` and `auditor` too. Every one of those baselines was
orphaned, and `MIN_RUNS = 5` then put a verdict ~12 builds (~$71 of token value) away,
which is why `area evals` could never return one. self-audit-2026-10-27.md M9.

Two halves, and the first is what makes the second honest:
  * `install_skills` is target-aware, so a plain app never RECEIVES the CF skill —
    previously `skills_preamble` declined to NAME it while the installer copied it in
    anyway, so a session in that directory could still discover it;
  * the digest's skills term is split by scope, so a domain skill versions only the
    kinds that install it.

docs/harness2-gap-assessment.md F2.
"""
import shutil

import pytest

from area import profile as P
from area import skills as S


@pytest.fixture
def pack(tmp_path, monkeypatch):
    """A real copy of the shipped pack, so this exercises the actual SKILL.md files."""
    d = tmp_path / "skills"
    shutil.copytree(S.SKILLS_DIR, d)
    monkeypatch.setattr(S, "SKILLS_DIR", d)
    P._profile_cache.clear() if hasattr(P, "_profile_cache") else None
    return d


def _edit(skill_dir):
    f = skill_dir / "SKILL.md"
    f.write_text(f.read_text() + "\n<!-- an edit -->\n")


# ---- the scope declaration ----------------------------------------------------

def test_the_shipped_pack_declares_one_universal_and_one_domain_skill(pack):
    scopes = {n: S.skill_targets(pack / n) for n in S.skill_names(pack)}
    assert scopes["area-oracle-loop"] == (), "the build discipline must stay universal"
    assert scopes["vinext-cf-build"] == ("cloudflare",)


@pytest.mark.parametrize("front,expected", [
    ("---\nname: x\ntargets: [cloudflare]\n---\n", ("cloudflare",)),
    ("---\nname: x\ntargets: cloudflare\n---\n", ("cloudflare",)),
    ("---\nname: x\n---\n", ()),                 # unscoped reads as universal
    ("no frontmatter at all\n", ()),
    ("---\nname: [unclosed\n", ()),              # malformed must not raise
    ("---\nname: x\ntargets: 7\n---\n", ()),     # wrong type must not raise
])
def test_scope_parsing_is_total(tmp_path, front, expected):
    d = tmp_path / "s"
    d.mkdir()
    (d / "SKILL.md").write_text(front)
    assert S.skill_targets(d) == expected


# ---- the install ---------------------------------------------------------------

def test_a_plain_build_never_receives_the_cloudflare_skill(pack, tmp_path):
    app = tmp_path / "apps" / "plainapp"
    installed = S.install_skills(app, src=pack, target="plain")
    assert installed == ["area-oracle-loop"]
    assert not (app / ".claude" / "skills" / "vinext-cf-build").exists(), \
        "the CF skill was copied into a plain app; it could still be discovered"


def test_a_cloudflare_build_receives_both(pack, tmp_path):
    app = tmp_path / "apps" / "cfapp"
    assert S.install_skills(app, src=pack, target="cloudflare") == \
        ["area-oracle-loop", "vinext-cf-build"]


def test_no_target_still_installs_everything(pack, tmp_path):
    """Every existing caller passes no target; none of them may change behaviour."""
    app = tmp_path / "apps" / "a"
    assert S.install_skills(app, src=pack) == S.skill_names(pack)


def test_the_prompt_and_the_directory_agree(pack, tmp_path):
    """One rule. The CF gate used to be hardcoded in `skills_preamble` while the
    installer copied everything, so the nudge and the app dir disagreed."""
    for target in ("plain", "cloudflare", "vercel"):
        app = tmp_path / "apps" / target
        installed = S.install_skills(app, src=pack, target=target)
        named = S.skills_preamble(target)
        for n in S.skill_names(pack):
            assert (f"/{n}" in named) == (n in installed), \
                f"{target}: /{n} named={f'/{n}' in named} installed={n in installed}"


# ---- the digest ----------------------------------------------------------------

def _digests(kinds):
    return {k: p.digest for k, p in P.all_profiles().items() if k in kinds}


def test_editing_the_domain_skill_moves_only_the_kinds_that_install_it(pack):
    inherited = ["e2e-author", "chaos-author", "auditor", "holdout-author"]
    before = _digests(["builder"] + inherited)

    _edit(pack / "vinext-cf-build")
    after = _digests(["builder"] + inherited)

    assert after["builder"] != before["builder"], \
        "the kind that INSTALLS the CF skill must be re-versioned by it"
    for k in inherited:
        assert after[k] == before[k], \
            f"{k} was re-versioned by a Cloudflare skill it cannot be reached by"


def test_editing_the_universal_skill_still_moves_every_participating_kind(pack):
    kinds = ["builder", "e2e-author", "chaos-author", "auditor", "holdout-author"]
    before = _digests(kinds)

    _edit(pack / "area-oracle-loop")
    after = _digests(kinds)

    for k in kinds:
        assert after[k] != before[k], f"{k} ignored an edit to the build discipline"


def test_a_kind_that_never_runs_where_the_pack_is_ignores_both(pack):
    none_kinds = ["spec-extractor", "product-reviewer", "researcher"]
    before = _digests(none_kinds)
    _edit(pack / "vinext-cf-build")
    _edit(pack / "area-oracle-loop")
    assert _digests(none_kinds) == before


# ---- and the attestation must NOT have shrunk ----------------------------------

def test_provenance_still_attests_the_whole_pack(pack):
    """A version answers "what can change this kind"; the attestation answers "what
    shaped this build". Narrowing the second would make provenance say less than the
    truth, so `skills_digest()` must still move for EITHER half."""
    from area import provenance as V

    base = V.skills_digest()
    _edit(S.SKILLS_DIR / "vinext-cf-build")
    after_domain = V.skills_digest()
    _edit(S.SKILLS_DIR / "area-oracle-loop")
    after_both = V.skills_digest()
    assert base != after_domain != after_both
    assert base != after_both
