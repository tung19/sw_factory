"""Spec artifact schema.

Contracts are the source of truth (PLAN.md): a requirement (or reverse-engineer
output) is distilled into a structured, validated spec + acceptance criteria.
Acceptance criteria are the testable "oracle" the build loop runs against.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from pydantic import BaseModel, Field


class EntityField(BaseModel):
    name: str
    type: str  # string | text | int | float | bool | datetime | enum | ...
    required: bool = True


class Entity(BaseModel):
    name: str
    fields: List[EntityField] = Field(default_factory=list)


class Feature(BaseModel):
    id: str  # kebab-case, e.g. "add-todo"
    title: str
    description: str


# How a criterion's "then" is to be proven. IEEE 1233 treats verifiability as a core
# attribute of a requirement and names these four methods; a criterion whose method
# cannot be stated is usually ambiguous or not worth the cost of verifying.
#
#   execution      — run the system and observe the stated outcome. The only method
#                    that can settle a RUNTIME claim.
#   inspection     — read the artifact (source, config, a manifest).
#   demonstration  — exercise it in a live environment (a browser, a deployed app).
#   analysis       — derive it (a type system, a proof, a measured budget).
#
# Why this exists: `expenses` AC-14 asserted "the app makes no outbound network
# requests" — a runtime property — and the locked holdout "verified" it by grepping
# source for HTTP client names. It passed while `next telemetry status` reported
# Enabled, and it later FAILED on a documentation URL inside a comment. Independent,
# frozen, and nearly powerless. AREA's spine is "quality <= strength + INDEPENDENCE of
# the oracle"; independence was enforced and strength was never measured, because
# nothing recorded what a criterion's proof was supposed to be.
VERIFY_METHODS = ("execution", "inspection", "demonstration", "analysis")


class AcceptanceCriterion(BaseModel):
    id: str  # e.g. "AC-1"
    feature: str  # must reference a Feature.id
    given: str
    when: str
    then: str
    # None = the spec did not state one. Reported as "method unstated", which is NOT
    # the same as "unverifiable" — it is the truth about specs written before this
    # field existed, and must not be silently defaulted to a method nobody chose.
    verify_by: Optional[str] = None


class UiEvidence(BaseModel):
    """Flow B: a POINTER to the reference app's captured UI under specs/<name>/_ui/.

    Deliberately NOT inline CSS/markup — only paths (relative to the _ui/ dir) plus
    extracted design tokens — so the spec stays small and the build prompt doesn't
    bloat (the vendored FILES are the channel to the builder, not this YAML). The
    pointer/evidence fields are filled by the deterministic capture step
    (area.re.ui_capture); the prose fields (description/palette/notes) are optional
    and may be emitted by the RE agent as observations — the files are the truth.
    """
    captured: bool = False             # the capture step ran and found UI
    source_kind: str = ""              # repo | path | url
    reference_url: str = ""            # the live reference (url kind only)
    dir: str = ""                      # path to the specs/<name>/_ui/ evidence dir
    rendered: List[str] = Field(default_factory=list)  # rendered markup files
    styles: List[str] = Field(default_factory=list)    # stylesheet files
    assets: List[str] = Field(default_factory=list)    # static asset files
    screenshot: str = ""               # reference.png baseline (url kind, if any)
    tokens: Dict[str, List[str]] = Field(default_factory=dict)  # colors/fonts/vars
    # Credential screening of the captured copy (area.screen). The reference is
    # UNTRUSTED, so a token sitting in an unrelated file must not ride into the
    # builder's context; `_sample/` stays byte-exact, these counts describe the COPY.
    redactions: int = 0
    redacted_files: List[str] = Field(default_factory=list)
    spa_caveat: bool = False           # plain fetch saw no client-rendered content
    description: str = ""              # optional, agent-emitted (prose)
    palette: List[str] = Field(default_factory=list)   # optional, agent-emitted
    notes: str = ""                    # capture reason / caveats


class Route(BaseModel):
    """A path the app serves. Flow B's reason for existing, but useful to every flow.

    A clone of `taskboard` reverse-engineered its features, entities, scrypt hash
    format and `sid` cookie correctly — and recorded NO route map, because `Spec` had
    nowhere to put one. Its own independent reviewer caught the consequence: AC-8 and
    AC-22 required "requesting a board URL directly" while no document said what that
    URL was, so the assumption on file was *"invent a plausible map"*. A parity holdout
    authored from that spec asserts against invented paths, the clone passes, and
    `verify-holdout-intact.sh` still reports the oracle intact — independent, frozen,
    and measuring something that does not exist.

    The real routes were readable from `_sample/app/` in a second: `/`, `/login`,
    `/boards`, `/boards/[id]`. Nothing was hard about discovering them; there was no
    field to write them in. Same shape as the missing `ui` field that #27/#28 added
    after "the clone's UI is wrong".
    """

    path: str                     # "/boards/[id]" — as served, params included
    purpose: str = ""             # what a visitor does there
    kind: str = "page"            # page | api | action


class Spec(BaseModel):
    name: str
    summary: str
    stack: str = "nextjs"
    entities: List[Entity] = Field(default_factory=list)
    features: List[Feature] = Field(default_factory=list)
    ui: Optional[UiEvidence] = None    # Flow B: captured reference-UI evidence (see above)
    # The paths the app serves. For a clone these are the REFERENCE's paths and
    # the clone must serve the same ones; `routes_unquoted` reports any criterion
    # that navigates without naming one. See Route for what went wrong without it.
    routes: List[Route] = Field(default_factory=list)


class Acceptance(BaseModel):
    criteria: List[AcceptanceCriterion] = Field(default_factory=list)


def load_spec(path: str | Path) -> Spec:
    return Spec.model_validate(yaml.safe_load(Path(path).read_text()))


def load_acceptance(path: str | Path) -> Acceptance:
    return Acceptance.model_validate(yaml.safe_load(Path(path).read_text()))



# Words that mean "the visitor went somewhere". A criterion containing one is making a
# claim about a PATH, so it has to say which — otherwise the holdout author (which sees
# only acceptance.yaml, never spec.yaml) invents one, and the frozen oracle then asserts
# against a route the app may not serve.
_NAVIGATES = re.compile(
    r"\b(visit|visits|visiting|navigat\w*|request\w*|open\w*|go(es)? to|redirect\w*|"
    r"lands? on|page at|url)\b", re.I)


def routes_unquoted(spec: Spec, acc: Acceptance) -> list[str]:
    """Criteria that navigate somewhere without naming a declared route.

    Reported, not fatal: plenty of criteria legitimately say "lands on the boards page"
    in prose while a sibling criterion pins the path. Blocking every one of them would
    be a false block. What must not happen silently is a whole spec that navigates and
    declares no paths at all — which is exactly what the `taskboard` clone produced.
    """
    paths = [r.path for r in spec.routes if r.path.startswith("/")]
    out: list[str] = []
    for c in acc.criteria:
        text = " ".join((c.given, c.when, c.then))
        if not _NAVIGATES.search(text):
            continue
        if not any(pp in text for pp in paths):
            out.append(c.id)
    return out

def validate_cross(spec: Spec, acc: Acceptance) -> list[str]:
    """Return a list of cross-reference problems (empty == valid)."""
    problems: list[str] = []
    feature_ids = {f.id for f in spec.features}
    if not spec.features:
        problems.append("spec.features is empty — at least one feature required")
    if not acc.criteria:
        problems.append("acceptance.criteria is empty — at least one AC required")
    for c in acc.criteria:
        if c.feature not in feature_ids:
            problems.append(
                f"acceptance {c.id}: feature '{c.feature}' not in spec.features "
                f"({sorted(feature_ids)})"
            )
    covered = {c.feature for c in acc.criteria}
    for fid in feature_ids - covered:
        problems.append(f"feature '{fid}' has no acceptance criterion")
    for r in spec.routes:
        if not r.path.startswith("/"):
            problems.append(
                f"spec.routes: {r.path!r} is not an absolute path (start it with '/')")
    # A spec whose criteria navigate while declaring NO routes is the taskboard-clone
    # failure: the oracle gets authored against invented paths. That one is fatal; a
    # single prose-only criterion is not (see routes_unquoted).
    if not spec.routes and routes_unquoted(spec, acc):
        problems.append(
            "spec.routes is empty but acceptance criteria navigate to pages "
            f"({', '.join(routes_unquoted(spec, acc)[:5])}…) — list the paths the app "
            "serves in spec.routes, and quote the literal path in any criterion that "
            "requests or redirects to one. Otherwise the independent holdout author, "
            "which never sees spec.yaml, invents the URLs and the frozen oracle asserts "
            "against routes the app may not serve.")
    return problems
