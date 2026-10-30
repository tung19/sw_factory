"""P0 — a deterministic lint for skill `description:` lines
(from superpowers:writing-skills/discovery.md: a description that summarizes the workflow
makes an agent follow the summary instead of loading the skill).

Only objective properties are enforced here: a trigger phrase is present, the description
stays within a word budget, and it carries no literal step-sequence (arrows / numbered
lists). Whether a description PROSE-summarizes the workflow is a judgment call left to the
`authoring-area-skills` skill — a regex for that has false positives (discovery.md says so),
so it is deliberately NOT enforced mechanically.
"""
from __future__ import annotations

import re

from area.paths import REPO

TREES = [REPO / ".claude" / "skills", REPO / "skills"]
WORD_CAP = 80


def _descriptions() -> dict[str, str]:
    out: dict[str, str] = {}
    for tree in TREES:
        if not tree.is_dir():
            continue
        for d in sorted(tree.iterdir()):
            sk = d / "SKILL.md"
            if not sk.is_file():
                continue
            m = re.search(r"^description:\s*(.+)$", sk.read_text(encoding="utf-8"),
                          re.MULTILINE)
            if m:
                out[f"{tree.name}/{d.name}"] = m.group(1).strip()
    return out


def test_every_skill_has_a_description() -> None:
    assert _descriptions(), "no skills with a description found"


def test_descriptions_have_a_trigger_phrase() -> None:
    for name, desc in _descriptions().items():
        assert re.search(r"use when(ever)?\b", desc, re.IGNORECASE), (
            f"{name}: a description must say WHEN to use the skill (\"Use when…\"), "
            f"not what it does")


def test_descriptions_within_word_budget() -> None:
    for name, desc in _descriptions().items():
        n = len(desc.split())
        assert n <= WORD_CAP, f"{name}: description is {n} words (cap {WORD_CAP})"


def test_descriptions_have_no_numbered_step_list() -> None:
    # A numbered list in a one-line description is an unambiguous workflow-in-the-trigger;
    # a single illustrative arrow (e.g. "requirement → build") is NOT, so arrows are left
    # to judgment (discovery.md warns a regex over-flags them).
    for name, desc in _descriptions().items():
        assert not re.search(r"\b[1-9]\.\s+\S+.*\b[1-9]\.\s", desc), (
            f"{name}: description has a numbered step list; the workflow belongs in the body")
