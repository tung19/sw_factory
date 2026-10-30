"""The skill the BUILDER gets must be the skill we maintain.

There are two skill trees, on purpose:

- `skills/` is the pack `area.skills.install_skills` copies into every generated app
  (`<app>/.claude/skills/`), so it is what the autonomous BUILD agent reads — and what
  `area.provenance.skills_digest()` hashes into the attestation.
- `.claude/skills/` is what the INTERACTIVE Claude Code agent reads in this repo. It
  additionally holds workflow skills (`build-from-docs`, `clone-from-source`) that drive
  the factory itself and have no meaning inside a generated app.

They drifted. `vinext-cf-build` was rewritten in `.claude/skills/` (2026-10-22) when
`area cf-fix`/`cf-clone` shipped, and the copy under `skills/` stayed at the 2026-10-19
text with zero mentions of either. So the deterministic CF automation the changelog
records as shipped never reached the build agent, and the attestation digested the stale
copy. Nothing detected it, because nothing compared the trees.

This is the same invariant CI already enforces for `area/net/static/index.html` vs
`coordinator-cf/public/index.html` — kept as a test so `make check` catches it locally
too, not only on a push.
"""
from pathlib import Path

import pytest

from area.paths import REPO

SHIPPED = REPO / "skills"
INTERACTIVE = REPO / ".claude" / "skills"

# Skills that exist ONLY for the interactive agent. Listed so adding one is deliberate:
# a new name appearing here must be a factory workflow, not domain knowledge the builder
# also needs.
INTERACTIVE_ONLY = {"build-from-docs", "clone-from-source", "authoring-area-skills"}


def _names(tree: Path) -> set[str]:
    return {p.name for p in tree.iterdir() if (p / "SKILL.md").exists()} if tree.is_dir() else set()


def test_both_trees_exist_and_the_shipped_pack_is_not_empty():
    assert _names(SHIPPED), "the builder would get no skills at all"
    assert _names(INTERACTIVE), "the interactive agent would get no skills at all"


@pytest.mark.parametrize("name", sorted(_names(SHIPPED) & _names(INTERACTIVE)))
def test_a_skill_in_both_trees_is_byte_identical(name):
    """One skill name, one text. A divergence here means the builder is being shipped
    something other than what we maintain and read."""
    for f in sorted((INTERACTIVE / name).rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(INTERACTIVE / name)
        other = SHIPPED / name / rel
        assert other.is_file(), f"{name}/{rel} is missing from skills/"
        assert other.read_bytes() == f.read_bytes(), (
            f"{name}/{rel} differs between the two trees — the build agent reads "
            f"skills/, the interactive agent reads .claude/skills/")


def test_the_interactive_only_set_is_exactly_what_we_declared():
    """Keeps the split honest: anything in .claude/skills/ but not shipped is either a
    declared factory workflow, or an accident."""
    extra = _names(INTERACTIVE) - _names(SHIPPED)
    assert extra == INTERACTIVE_ONLY, (
        f"undeclared interactive-only skill(s): {sorted(extra - INTERACTIVE_ONLY)}; "
        f"missing: {sorted(INTERACTIVE_ONLY - extra)}")


def test_the_attestation_digests_the_tree_the_builder_actually_gets():
    """`skills_digest()` must hash `skills/` — the shipped pack. Hashing the other tree
    would attest knowledge the build never saw."""
    from area import provenance, skills

    assert skills.SKILLS_DIR == SHIPPED
    d = provenance.skills_digest()
    assert d and d.startswith("sha256:") and len(d) == len("sha256:") + 64

    # and it is sensitive to the shipped content, or it attests nothing
    probe = SHIPPED / "area-oracle-loop" / "SKILL.md"
    original = probe.read_bytes()
    try:
        probe.write_bytes(original + b"\n<!-- digest probe -->\n")
        assert provenance.skills_digest() != d
    finally:
        probe.write_bytes(original)
    assert provenance.skills_digest() == d


def test_the_builder_is_told_about_the_automation_that_exists():
    """The content assertion that would have caught the drift: `area cf-fix` and
    `area cf-clone` are real CLI commands, so the CF skill the builder reads must name
    them — and must also give the manual route, because the `area` CLI is not
    guaranteed to be on PATH inside a generated app."""
    text = (SHIPPED / "vinext-cf-build" / "SKILL.md").read_text()
    assert "area cf-fix" in text and "area cf-clone" in text
    assert "npm ls workerd" in text, "no manual route for the compat-date pin"
