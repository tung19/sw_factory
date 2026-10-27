"""area.build.ui_vendor — vendor the captured reference UI into the clone.

Flow B parity: the RE step snapshots the reference's real stylesheets / design
tokens / static assets / rendered markup into `specs/<name>/_ui/`. We copy that
evidence into `<app>/.area-ui/` (a reference staging dir, NOT the app routes) and
prepend a prompt block telling the build agent to REPRODUCE that look rather than
re-invent it. Mirrors area.skills.install_skills/skills_preamble. Idempotent; a
no-op when there is no evidence.
"""
from __future__ import annotations

import shutil
from pathlib import Path

VENDOR_DIR = ".area-ui"
_SUBDIRS = ("styles", "assets", "rendered")
_FILES = ("tokens.json", "manifest.yaml")


def install_ui_evidence(app_dir: str | Path, ui_dir: str | Path) -> list[str]:
    """Copy `ui_dir`'s evidence into `<app_dir>/.area-ui/`. Idempotent.
    Returns the names copied (empty when there is nothing to vendor)."""
    ui = Path(ui_dir)
    if not ui.is_dir():
        return []
    dest = Path(app_dir) / VENDOR_DIR
    copied: list[str] = []
    for sub in _SUBDIRS:
        s = ui / sub
        if s.is_dir() and any(s.iterdir()):
            shutil.copytree(s, dest / sub, dirs_exist_ok=True)
            copied.append(sub)
    for f in _FILES:
        p = ui / f
        if p.is_file():
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest / f)
            copied.append(f)
    return copied


def ui_preamble(copied: list[str]) -> str:
    """Prompt block nudging the builder to reproduce the vendored reference look."""
    if not copied:
        return ""
    return (
        "=== VISUAL PARITY — the reference UI is vendored, REPRODUCE it ===\n"
        f"The reference app's REAL UI is vendored under {VENDOR_DIR}/ : its "
        "stylesheets (styles/), static assets (assets/), rendered markup "
        "(rendered/) and design tokens (tokens.json). This is a PARITY clone — "
        "match the reference's look; do NOT invent a different design.\n"
        f"- Bring the stylesheets and assets from {VENDOR_DIR}/ into the app "
        "(e.g. app/globals.css, public/) and actually apply them.\n"
        "- Reproduce the rendered markup's STRUCTURE, class names and layout in "
        "your components as faithfully as the framework allows.\n"
        "- Treat the colors / fonts / variables in tokens.json as the design tokens.\n"
        f"- {VENDOR_DIR}/ is reference material only: do NOT serve it as a route and "
        "keep it out of the build output.\n\n"
    )
