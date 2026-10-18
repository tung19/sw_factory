"""Small shared helpers."""
from __future__ import annotations

import re


def safe_name(name: str, *, default: str = "app") -> str:
    """Sanitize a project name into a single safe path segment.

    Strips anything but [A-Za-z0-9_-], which removes path separators and dots,
    so a crafted name (e.g. "../../etc") cannot traverse out of workspace/.
    """
    s = re.sub(r"[^A-Za-z0-9_-]", "-", (name or "").strip()).strip("-_")
    return s or default
