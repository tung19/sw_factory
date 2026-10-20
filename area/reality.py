"""area.reality — the show→react→refine loop (recommendation #4).

A good product from an UNCLEAR requirement is never a one-shot: the user has to SEE
what was built, against the GUESSES the build had to make, and refine. After a green
build AREA now prints exactly that — the assumptions it chose, how to preview the app,
and the one command to course-correct — so the human closes the intent loop instead of
discovering a wrong guess later.

Pure + unit-tested: `build_reality_report` just formats strings; the CLI prints it.
"""
from __future__ import annotations

from pathlib import Path

from area.spec.extract import load_assumptions


def build_reality_report(name: str, spec_dir: str | Path, app_dir: str | Path,
                         *, deployed_url: str | None = None) -> str:
    """Format the post-build reality check: the assumptions the build made, how to
    preview it, and the iterate command to refine. Returns a printable block."""
    lines: list[str] = ["", "[area] ── reality check: did we build what you meant? ──"]

    assumptions = load_assumptions(spec_dir)
    if assumptions:
        material = [a for a in assumptions if str(a.get("material")).lower() == "true"]
        shown = material or assumptions
        label = "MATERIAL assumptions this build chose" if material else "assumptions this build chose"
        lines.append(f"[area] {label} (confirm they match your intent):")
        for a in shown[:8]:
            q = str(a.get("question", "")).strip()
            guess = str(a.get("assumption", "")).strip()
            lines.append(f"[area]   • {q}  →  assumed: {guess}")
    else:
        lines.append("[area] (no ambiguities were recorded — the requirement read as clear)")

    if deployed_url:
        lines.append(f"[area] preview (live): {deployed_url}")
    else:
        lines.append(f"[area] preview locally: (cd {app_dir} && npm run dev)")

    lines.append("[area] not what you meant? refine it (re-locks the oracle, rebuilds):")
    lines.append(f'[area]   area iterate {name} "<what to change>"')
    return "\n".join(lines)
