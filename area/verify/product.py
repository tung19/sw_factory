"""area.verify.product — PRODUCT-FIT gate (recommendation #3).

The other gates prove the app is built RIGHT (holdout/audit/chaos/e2e/nfr). None ask
the product question: did we build the RIGHT thing, WELL? This gate has an INDEPENDENT
keyless reviewer read the spec + the built app and judge, per feature, whether the app
actually delivers it, plus obvious UX / fit gaps (dead features, missing empty/error
states, unlabeled inputs, nothing a user can actually do).

Posture mirrors audit tier-2 / nfr: ADVISORY by default (reports a verdict + gaps,
never blocks), and only BLOCKS when `strict=True` and the verdict is "concerns".
Fail-open: an unavailable reviewer passes with a skip note — a product opinion must
never wedge the pipeline.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

import yaml

from area.engine import ask_cli

from area.paths import WORKSPACE  # noqa: E402 (AREA_WORKSPACE-aware single source)
SENTINEL = "<<<PRODUCT>>>"
_APP_GLOBS = ("app/**/*.tsx", "app/**/*.ts", "components/**/*.tsx", "*.html", "index.html")
_MAX_FILES = 12
_PER_FILE = 1600


def _app_excerpt(app_dir: Path) -> str:
    """A bounded excerpt of the built app's user-facing source (no node_modules)."""
    parts: list[str] = []
    seen = 0
    for pat in _APP_GLOBS:
        for f in sorted(app_dir.glob(pat)):
            if "node_modules" in f.parts or ".next" in f.parts or not f.is_file():
                continue
            try:
                txt = f.read_text()[:_PER_FILE]
            except Exception:
                continue
            parts.append(f"--- {f.relative_to(app_dir)} ---\n{txt}")
            seen += 1
            if seen >= _MAX_FILES:
                return "\n\n".join(parts)
    return "\n\n".join(parts)


def _product_prompt(spec_text: str, acc_text: str, app_excerpt: str) -> str:
    """Pure. The independent product-fit reviewer's single-shot prompt."""
    return (
        "You are an INDEPENDENT product reviewer for a software factory. The code "
        "already passes its technical tests; your ONLY job is to judge whether the "
        "built app actually delivers the PRODUCT the spec describes, and whether it "
        "would be usable. For EACH spec feature, decide if the app visibly delivers "
        "it. Flag real UX/fit gaps: a declared feature with no UI, no empty/error "
        "state, unlabeled inputs, or nothing a user can actually accomplish. Ignore "
        "style nitpicks and anything already covered by tests.\n\n"
        f"=== spec.yaml ===\n{spec_text.strip()}\n\n"
        f"=== acceptance.yaml ===\n{acc_text.strip()}\n\n"
        f"=== BUILT APP (excerpt) ===\n{app_excerpt.strip() or '(no user-facing source found)'}\n\n"
        "Output ONLY the sentinel on its own line, then YAML, nothing after:\n"
        f"{SENTINEL}\n"
        "verdict: ok            # 'ok' if it delivers the product; 'concerns' if not\n"
        "coverage: <delivered>/<total features>\n"
        "gaps:                  # [] if none\n"
        "  - <a concrete product/UX gap>\n"
    )


def _parse_verdict(raw: str) -> dict[str, Any]:
    """Pure. Parse the reviewer's reply into {verdict, coverage, gaps, parsed}. Never
    raises. On unusable output it returns a passing verdict with **parsed=False** —
    callers MUST check that flag, or they report a pass for a reply nobody understood
    (`product_verify._unmeasurable` is what does)."""
    text = (raw or "").strip()
    if SENTINEL in text:
        text = text.split(SENTINEL, 1)[1].strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if "```" in text:
            text = text.rsplit("```", 1)[0]
    try:
        data = yaml.safe_load(text)
    except Exception:
        data = None
    if not isinstance(data, dict):
        return {"verdict": "ok", "coverage": "?", "gaps": [], "parsed": False}
    verdict = str(data.get("verdict", "ok")).strip().lower()
    verdict = "concerns" if verdict.startswith("concern") else "ok"
    gaps = data.get("gaps") or []
    if not isinstance(gaps, list):
        gaps = [str(gaps)]
    gaps = [str(g).strip() for g in gaps if str(g).strip()]
    return {"verdict": verdict, "coverage": str(data.get("coverage", "?")),
            "gaps": gaps, "parsed": True}


def _unmeasurable(why: str, strict: bool) -> bool:
    """The gate could not form a verdict. Under --strict that is a FAILURE, because an
    enforced gate that cannot measure must not report a pass (the rule nfr/visual
    already follow). Otherwise it stays advisory, but says plainly that nothing was
    measured rather than printing a passing verdict."""
    if strict:
        print(f"[area] product: ❌ BLOCK (--strict) — {why}, so no verdict was formed")
        return False
    print(f"[area] product: — {why}; nothing measured (advisory, use --strict to "
          "enforce)")
    return True


def product_verify(name: str, *, backend: str = "acp", model: Optional[str] = None,
                   strict: bool = False, ask: Optional[Callable[[str], str]] = None,
                   root: Optional[str | Path] = None) -> bool:
    """Product-fit review of a built app (did we build the RIGHT thing?).

    Advisory by default: it prints and passes. Under `--strict` it enforces, and that
    now includes the cases where it could NOT measure — no spec, an unavailable
    reviewer, or a reply it could not parse. The same rule the nfr/visual gates
    follow: a floor you asked to be enforced but that could not be measured must FAIL
    loudly, not silently pass.

    That last case mattered most: `_parse_verdict` returns a PASSING verdict with
    `parsed=False` when the reply is unusable, and nothing read that flag — so the
    gate could print "✅ verdict=ok" about output it never understood, which is a
    false green in a gate."""
    base = Path(root) if root else WORKSPACE
    spec_dir, app_dir = base / "specs" / name, base / "apps" / name
    try:
        spec_text = (spec_dir / "spec.yaml").read_text()
        acc_text = (spec_dir / "acceptance.yaml").read_text()
    except Exception:
        return _unmeasurable("no spec to review", strict)
    prompt = _product_prompt(spec_text, acc_text, _app_excerpt(app_dir))
    try:
        res = _parse_verdict((ask or (lambda p: ask_cli(p, model=model, label="product")))(prompt))
    except Exception as e:  # noqa: BLE001 — advisory unless --strict
        return _unmeasurable(f"reviewer unavailable ({type(e).__name__})", strict)
    if not res.get("parsed", True):
        return _unmeasurable("the reviewer's reply could not be parsed", strict)
    icon = "✅" if res["verdict"] == "ok" else "⚠️"
    print(f"[area] product: {icon} verdict={res['verdict']} coverage={res['coverage']}")
    for g in res["gaps"]:
        print(f"[area]   • gap: {g}")
    if res["verdict"] == "concerns" and strict:
        print("[area] product: ❌ BLOCK (--strict) — product-fit concerns above")
        return False
    if res["verdict"] == "concerns":
        print("[area] product: advisory only (not blocking); pass --strict to enforce")
    return True
