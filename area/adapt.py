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
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional, Protocol, TypeVar

import yaml

from area.paths import WORKSPACE
from area.research import ResearchBrief, research
from area.seed import SeedPolicy, SeedResult, seed_from_reference
from area.spec.models import Acceptance, AcceptanceCriterion, Feature, Spec

if TYPE_CHECKING:
    from area.engine_util import Backend

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


# ---- P3: the data dimension ---------------------------------------------------
# The built app's data concern, synthesized from how the researched top repos
# handle data (storage / integration / source), with the requirement overriding.
# Feeds (i) acceptance criteria (durable persistence + an ingest feature) and
# (ii) a build-prompt fragment; provisioning (DB + schema) reuses area.deploy.

@dataclass
class DataPlan:
    storage: str          # e.g. "postgres", "sqlite/D1"
    integration: str      # e.g. "batch ETL", "webhook", "none"
    source: str           # e.g. "CSV upload", "REST API", "user input"
    entities: list[str] = field(default_factory=list)


def _majority(values: list[str], default: str) -> str:
    vals = [v.strip() for v in values if v and v.strip()]
    if not vals:
        return default
    return Counter(vals).most_common(1)[0][0]


def synthesize_data_plan(
    brief: ResearchBrief, *, storage: Optional[str] = None,
    integration: Optional[str] = None, source: Optional[str] = None,
    entities: Optional[list[str]] = None,
) -> DataPlan:
    """A requirement-anchored data plan: a value the requirement pins (the
    `storage`/`integration`/`source` overrides) WINS; otherwise take the majority
    choice across the researched top repos' data analysis; else a safe default."""
    return DataPlan(
        storage=storage or _majority([r.data_storage for r in brief.top], "sqlite/D1"),
        integration=integration or _majority([r.data_integration for r in brief.top], "none"),
        source=source or _majority([r.data_source for r in brief.top], "user input"),
        entities=list(entities or []),
    )


def _has_ingest(plan: DataPlan) -> bool:
    return plan.integration.strip().lower() not in ("", "none", "n/a")


def data_acceptance(plan: DataPlan, *, start_index: int = 5) -> list[AcceptanceCriterion]:
    """Acceptance criteria for the data dimension: durable persistence always, plus
    an ingest/ETL criterion when the plan calls for an integration (AC-5)."""
    acs = [AcceptanceCriterion(
        id=f"AC-{start_index}", feature="data-persistence",
        given="the app has stored records", when="the server restarts",
        then=f"the records survive (durable {plan.storage})")]
    if _has_ingest(plan):
        acs.append(AcceptanceCriterion(
            id=f"AC-{start_index + 1}", feature="data-ingest",
            given=f"a {plan.source} input in {plan.integration} form",
            when="it is ingested", then="the records appear in the app's store"))
    return acs


def data_build_notes(plan: DataPlan) -> str:
    """A build-prompt fragment telling the agent what data layer to build."""
    notes = [f"Persist data durably in {plan.storage} (must survive a restart)."]
    if _has_ingest(plan):
        notes.append(f"Provide an ingest/ETL feature that imports {plan.source} data "
                     f"via {plan.integration} into the store.")
    if plan.entities:
        notes.append(f"Core entities: {', '.join(plan.entities)}.")
    return " ".join(notes)


# ---- capstone: the `area adapt` pipeline --------------------------------------

@dataclass
class AdaptResult:
    name: str
    reference: str
    requirement: str
    spec: Spec
    acceptance: Acceptance
    provenance: dict[str, str]
    data_plan: DataPlan
    brief: ResearchBrief
    build_notes: str
    clarify_items: list[dict[str, Any]] = field(default_factory=list)
    clarify_needed: bool = False
    spec_dir: Optional[Path] = None
    seed: Optional[SeedResult] = None


def _write_spec(spec_dir: Path, spec: Spec, acc: Acceptance, brief: ResearchBrief,
                notes: str) -> None:
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "spec.yaml").write_text(yaml.safe_dump(spec.model_dump(), sort_keys=False))
    (spec_dir / "acceptance.yaml").write_text(
        yaml.safe_dump(acc.model_dump(), sort_keys=False))
    (spec_dir / "adapt-notes.md").write_text(
        f"# adapt build notes\n\n{notes}\n\n## research brief\n"
        f"- reference: {brief.reference}\n- candidates considered: "
        f"{brief.candidates_considered}\n- top repos: "
        + ", ".join(r.repo or r.url for r in brief.top) + "\n")


def adapt_pipeline(
    reference: str, requirement: str, *, name: str,
    requirement_features: Optional[list[Feature]] = None,
    reference_features: Optional[list[Feature]] = None, summary: str = "",
    backend: "Backend" = "acp", model: Optional[str] = None,
    budget: Optional[float] = None, count: int = 100, top: int = 5,
    researcher: Optional[Callable[[str, Path], None]] = None,
    clarify: bool = True,
    confirm: Optional[Callable[["AdaptResult"], bool]] = None,
    seed_policy: Optional[SeedPolicy] = None,
    seed_records: Optional[list[dict[str, Any]]] = None,
    workspace: Optional[str | Path] = None,
) -> AdaptResult:
    """Compose `area adapt`: P1 research → P2 requirement-anchored synthesis → P3
    data dimension → one-shot clarify → write spec+acceptance (the build handoff) →
    P4 opt-in seed. The agent steps (research, reference RE) are INJECTED
    (`researcher` / `reference_features`) so the composition is testable agent-free;
    the live build happens via the printed `area intake` handoff (reuses the
    oracle-loop) and the seed fetch is upstream."""
    root = Path(workspace) if workspace else WORKSPACE
    spec_dir = root / "specs" / name
    brief = research(reference, requirement, backend=backend, model=model,
                     budget=budget, count=count, top=top,
                     workspace=spec_dir / "research", runner=researcher)
    feats, prov = synthesize_features(requirement_features or [],
                                      reference_features or [], brief)
    plan = synthesize_data_plan(brief)
    acc = Acceptance(criteria=data_acceptance(plan))
    spec = Spec(name=name, summary=summary or requirement[:200], features=feats)
    result = AdaptResult(
        name=name, reference=reference, requirement=requirement, spec=spec,
        acceptance=acc, provenance=prov, data_plan=plan, brief=brief,
        build_notes=data_build_notes(plan), clarify_items=clarify_payload(prov),
        spec_dir=spec_dir)
    # P5 one-shot clarify: stop when the requirement was SILENT (auto-filled from
    # reference/research) unless the human confirms the filled spec.
    if clarify and auto_filled(prov) and (confirm is None or not confirm(result)):
        result.clarify_needed = True
        return result
    _write_spec(spec_dir, spec, acc, brief, result.build_notes)
    # P4 opt-in seed (area.seed enforces attestation + robots/PII/cap)
    if seed_policy is not None:
        result.seed = seed_from_reference(reference, seed_records or [], seed_policy)
    return result
