"""area.feature_map — a human-readable map of what a built app does and how to reach it.

pstack/Lauren's "Feature Map": condensed memory for an agent (and a human) — every
feature, the route(s) it lives at, the acceptance criteria that pin it, and how each is
verified. Derived PURELY from spec.yaml + acceptance.yaml (the oracle), so it can never
drift from the contract, and it is regenerated on every build/iterate.

It is written to specs/<name>/FEATURE_MAP.md — NOT into the app's source tree — so it
never changes the artifact digest / provenance (the .area-lesson.md lesson).

A leaf module: stdlib + area.spec.models only, no engine/SDK import, so any stage can
emit it without pulling the agent in.
"""
from __future__ import annotations

import re
from pathlib import Path

from area.spec.models import Acceptance, AcceptanceCriterion, Spec

FEATURE_MAP_REL = "FEATURE_MAP.md"


def _reaches(text: str, routes: list[str]) -> list[str]:
    """Declared routes whose path appears as a PATH TOKEN in an AC's text — i.e. the
    paths this criterion exercises. Uses the same boundary match as the contract gate
    (area.spec.models._names_a_path) so a declared "/" matches a standalone "/" but not
    the "/" inside "/login"."""
    return [r for r in routes
            if r and re.search(rf"(?<![\w/]){re.escape(r)}(?![\w])", text)]


def _one_line(s: str) -> str:
    return " ".join((s or "").split())


def _cell(s: str) -> str:
    """A value safe to drop into a markdown table cell: collapse whitespace and escape
    pipes, so an enum like `todo|doing|done` (or "list | grid") can't open phantom
    columns and corrupt the very map this file exists to keep legible."""
    return _one_line(s).replace("|", "\\|")


def render(spec: Spec, acc: Acceptance) -> str:
    route_paths = [r.path for r in spec.routes]
    lines: list[str] = []
    lines.append(f"# Feature map — {spec.name}")
    lines.append("")
    lines.append(
        f"> Generated from `spec.yaml` + `acceptance.yaml` — {len(spec.features)} "
        f"features · {len(acc.criteria)} acceptance criteria · {len(spec.routes)} "
        "routes. Regenerated on every build/iterate; edits here are overwritten.")
    lines.append("")
    if spec.summary:
        lines.append(_one_line(spec.summary))
        lines.append("")
    lines.append(f"**Stack:** {spec.stack}")
    lines.append("")

    # Routes — where the app lives.
    lines.append("## Routes")
    lines.append("")
    if spec.routes:
        lines.append("| Path | Kind | Purpose |")
        lines.append("|------|------|---------|")
        for r in spec.routes:
            lines.append(f"| `{r.path}` | {_cell(r.kind)} | {_cell(r.purpose) or '—'} |")
    else:
        lines.append("_No routes declared._")
    lines.append("")

    # Data model — the state the agent should know about.
    if spec.entities:
        lines.append("## Data")
        lines.append("")
        for e in spec.entities:
            fields = ", ".join(
                f"{f.name}:{f.type}{'' if f.required else '?'}" for f in e.fields)
            lines.append(f"- **{e.name}** — {fields or '(no fields listed)'}")
        lines.append("")

    # Features — each with the criteria that pin it and how to reach them.
    lines.append("## Features")
    lines.append("")
    by_feature: dict[str, list[AcceptanceCriterion]] = {}
    for c in acc.criteria:
        by_feature.setdefault(c.feature, []).append(c)
    for f in spec.features:
        lines.append(f"### {f.title} (`{f.id}`)")
        lines.append("")
        if f.description:
            lines.append(_one_line(f.description))
            lines.append("")
        crits = by_feature.get(f.id, [])
        if crits:
            lines.append("| AC | Verify | Reaches | Behaviour |")
            lines.append("|----|--------|---------|-----------|")
            for c in crits:
                text = " ".join((c.given, c.when, c.then))
                reach = ", ".join(f"`{p}`" for p in _reaches(text, route_paths)) or "—"
                behaviour = _cell(f"when {c.when} → {c.then}")
                verify = _cell(c.verify_by or "—")
                lines.append(f"| {_cell(c.id)} | {verify} | {reach} | {behaviour} |")
        else:
            lines.append("_No acceptance criterion — the contract would reject this._")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_feature_map(spec: Spec, acc: Acceptance, spec_dir: str | Path) -> Path:
    """Render and write specs/<name>/FEATURE_MAP.md. Returns the path written."""
    d = Path(spec_dir)
    d.mkdir(parents=True, exist_ok=True)
    out = d / FEATURE_MAP_REL
    out.write_text(render(spec, acc))
    return out
