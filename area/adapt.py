"""area.adapt — P2 of `area adapt`: synthesize a REQUIREMENT-ANCHORED spec from the
requirement (authoritative) + the reference RE + the research brief, tagging each
item with its SOURCE, and build the one-shot clarify payload.

Merge rule (AC-2): the REQUIREMENT WINS on conflict — an item whose id the
requirement defines keeps the requirement's version; otherwise the reference fills
it, else research. Provenance (`{id: source}`) lets the clarify gate show which
decisions were auto-filled from reference/research so the human confirms once
(AC-3) and every item is traceable to a source (AC-4).

Deterministic + agent-free: the NL→structured extraction of the requirement /
reference happens upstream (area.spec / area.re); this module merges the already-
structured items. The full `area adapt` pipeline (P1 research → P2 synthesis →
clarify → build) is wired in the capstone.
"""
from __future__ import annotations

import re
from typing import Any, Protocol, TypeVar

from area.research import ResearchBrief
from area.spec.models import Feature

SOURCE_REQUIREMENT = "requirement"
SOURCE_REFERENCE = "reference"
SOURCE_RESEARCH = "research"


class _HasId(Protocol):
    id: str


T = TypeVar("T", bound=_HasId)


def merge_by_source(sources: list[tuple[str, list[T]]]) -> tuple[list[T], dict[str, str]]:
    """Merge id-bearing items from `sources` given in PRIORITY order (the first
    occurrence of an id wins). Returns (merged items in priority/first-seen order,
    `{id: source_label}`). Generic over Feature / AcceptanceCriterion (both have
    `.id`), so the same requirement-wins rule covers features and acceptance."""
    merged: list[T] = []
    provenance: dict[str, str] = {}
    for label, items in sources:
        for it in items:
            if it.id not in provenance:
                provenance[it.id] = label
                merged.append(it)
    return merged, provenance


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "feature"


def features_from_brief(brief: ResearchBrief) -> list[Feature]:
    """Candidate features distilled from the research brief's top repos (dedup by
    slug; the description records which repos exhibited the feature)."""
    seen: dict[str, list[str]] = {}
    for repo in brief.top:
        for feat in repo.features:
            seen.setdefault(_slug(feat), []).append(repo.repo or repo.url or "?")
    out: list[Feature] = []
    for slug, repos in seen.items():
        out.append(Feature(id=slug, title=slug.replace("-", " "),
                           description=f"from research ({', '.join(repos[:3])})"))
    return out


def synthesize_features(
    requirement: list[Feature], reference: list[Feature], brief: ResearchBrief,
) -> tuple[list[Feature], dict[str, str]]:
    """Requirement-anchored feature set: requirement wins, then the reference, then
    research fills the remaining gaps. Returns (features, `{id: source}`)."""
    return merge_by_source([
        (SOURCE_REQUIREMENT, requirement),
        (SOURCE_REFERENCE, reference),
        (SOURCE_RESEARCH, features_from_brief(brief)),
    ])


def auto_filled(provenance: dict[str, str]) -> list[str]:
    """Ids the requirement was SILENT on (filled from reference/research) — the
    decisions the one-shot clarify gate asks the human to confirm."""
    return [iid for iid, src in provenance.items() if src != SOURCE_REQUIREMENT]


def clarify_payload(provenance: dict[str, str]) -> list[dict[str, Any]]:
    """One-shot clarify-gate content: every synthesized item + its source, with the
    auto-filled (non-requirement) ones flagged for confirmation."""
    return [{"id": iid, "source": src, "auto_filled": src != SOURCE_REQUIREMENT}
            for iid, src in provenance.items()]
