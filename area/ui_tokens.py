"""area.ui_tokens — design-token extraction from CSS text. A LEAF module.

Shared by the Flow-B UI capture (area.re.ui_capture, which writes the reference's
tokens) and the visual-parity gate (area.verify.visual, which reads the clone's).

It lives at the top level, stdlib-only and importing nothing of AREA, so a
deterministic measurement never has to depend on the RE/agent stack: importing
`area.re.ui_capture` (the obvious place to borrow this from) executes
`area/re/__init__.py` → `spec_from_source` → `area.engine` → the OpenHands SDK.
Measured: this leaf imports in ~1ms with no SDK, vs ~2s with. Honest caveat — a
gate reached through `area.verify` loads the SDK anyway, because that package's
__init__ imports the agent-driven gates (holdout/e2e/chaos); this keeps the
DEPENDENCY DIRECTION clean rather than claiming a load-time win for the gate.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

_RE_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_RE_FUNC_COLOR = re.compile(r"\b(?:rgba?|hsla?)\([^)]*\)", re.IGNORECASE)
_RE_FONT = re.compile(r"font-family\s*:\s*([^;}{]+)", re.IGNORECASE)
_RE_VAR = re.compile(r"(--[A-Za-z0-9_-]+)\s*:\s*([^;}{]+)")
# The `font:` SHORTHAND also carries the family list, and plenty of real CSS uses
# only that (found dogfooding: example.com ships `font:16px/1.6 system-ui,sans-serif`
# and nothing else, so a font-family-only parse scored 0 fonts). `\bfont\s*:` cannot
# match `font-family:`/`font-size:` — the `-` sits where the colon must be.
_RE_FONT_SHORTHAND = re.compile(r"\bfont\s*:\s*([^;}{]+)", re.IGNORECASE)
_RE_SIZE_TOKEN = re.compile(
    r"^[\d.]+(?:px|r?em|%|pt|pc|in|cm|mm|vh|vw|ch|ex)?(?:/[\d.]+[a-z%]*)?$",
    re.IGNORECASE,
)

CAP = 80  # per-category ceiling: tokens are a fingerprint, not a full inventory


def dedup(items: Iterable[str], cap: int = CAP) -> list[str]:
    """Order-preserving de-duplication, capped."""
    seen: dict[str, None] = {}
    for it in items:
        s = it.strip()
        if s and s not in seen:
            seen[s] = None
        if len(seen) >= cap:
            break
    return list(seen)


def _families_from_shorthand(value: str) -> list[str]:
    """Family list out of a `font:` shorthand value.

    Grammar: `[style] [variant] [weight] [stretch] <size>[/<line-height>] <families>`
    — so everything after the size token is the family list. A keyword-only value
    (`font: inherit`, `font: menu`) has no size token and yields nothing.
    """
    parts = value.split()
    for i, tok in enumerate(parts):
        if _RE_SIZE_TOKEN.match(tok):
            return " ".join(parts[i + 1:]).split(",")
    return []


def extract_tokens(css: str) -> dict[str, list[str]]:
    """Pull design tokens out of CSS text: colors, font families, CSS variables."""
    colors: list[str] = _RE_HEX.findall(css) + _RE_FUNC_COLOR.findall(css)
    decls: list[str] = _RE_FONT.findall(css)
    fams: list[str] = []
    for decl in decls:
        fams += decl.split(",")
    for decl in _RE_FONT_SHORTHAND.findall(css):
        fams += _families_from_shorthand(decl)
    fonts: list[str] = []
    for fam in fams:
        f = fam.strip().strip("'\"")
        if f and not f.startswith("var("):
            fonts.append(f)
    variables = [f"{n.strip()}: {v.strip()}" for n, v in _RE_VAR.findall(css)]
    return {
        "colors": dedup(c.lower() for c in colors),
        "fonts": dedup(fonts),
        "vars": dedup(variables),
    }


def merge_tokens(acc: dict[str, list[str]], more: dict[str, list[str]]) -> None:
    """Fold `more` into `acc` in place, de-duplicated and capped."""
    for k, vs in more.items():
        cur = acc.setdefault(k, [])
        for v in vs:
            if v not in cur and len(cur) < CAP:
                cur.append(v)
