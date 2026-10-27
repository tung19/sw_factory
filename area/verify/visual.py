"""area.verify.visual — the VISUAL-PARITY gate for Flow B clones (part C).

Behavior and look are graded separately: the holdout/e2e oracles assert behavior
through the public surface and are blind to pixels, so — per the spine, quality <=
strength + independence of the oracle — a clone's UI was free to drift while still
going oracle-green. This gate measures how close the clone LOOKS to the reference
captured in `specs/<name>/_ui/` (see area.re.ui_capture, part A).

Three layers, degrading by what the reference allows:
  1. tokens  — reference design tokens (colors/fonts) present in the clone's CSS.
  2. dom     — normalized tag+class skeleton similarity (reference markup vs the
               clone's markup; the clone's RENDERED html is used when the pixel
               layer booted it, else its JSX source).
  3. pixel   — screenshot diff, live-URL references only (we may not boot an
               untrusted repo), opt-in, and skipped gracefully with a reason.

Deterministic (no agent — this is a measurement, like nfr/perf) and ADVISORY by
default: it prints a score + writes artifacts and returns True. Commit
`specs/<name>/visual.yaml` (or pass --strict) to make a breach BLOCK. As in
area.verify.nfr, a COMMITTED threshold we could not measure fails loudly rather
than silently passing.
"""
from __future__ import annotations

import difflib
import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Optional

import yaml

from area._util import safe_name
from area.paths import WORKSPACE  # noqa: E402 (leaf single-source; see area.verify.e2e)
from area.ui_tokens import extract_tokens  # leaf: no agent/SDK import behind a gate

VISUAL_DIR = ".visual"
DEFAULT_MIN_SIMILARITY = 0.75
_WEIGHTS = {"pixel": 0.5, "dom": 0.3, "tokens": 0.2}

_TEMPLATE_DIFF = Path(__file__).resolve().parent / "templates" / "visual_diff.mjs"
_SKIP_DIRS = {"node_modules", ".git", ".next", "dist", "build", "out", ".visual",
              ".area-ui", "coverage", ".turbo", ".vercel"}
_CLONE_CSS_GLOBS = ("*.css", "app/**/*.css", "src/**/*.css", "styles/**/*.css",
                    "tailwind.config.js", "tailwind.config.ts")
_CLONE_MARKUP_GLOBS = ("app/**/layout.tsx", "app/**/page.tsx", "app/**/page.jsx",
                       "src/app/**/layout.tsx", "src/app/**/page.tsx",
                       "pages/**/*.tsx", "pages/**/*.jsx", "index.html")


# --------------------------------------------------------------------------- #
# pure: skeletons + scores
# --------------------------------------------------------------------------- #
class _Skeleton(HTMLParser):
    """Collect a tag+class skeleton of an HTML document (text/attrs stripped)."""

    def __init__(self) -> None:
        super().__init__()
        self.tokens: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        d = {k: (v or "") for k, v in attrs}
        cls = " ".join(sorted(d.get("class", "").split()))
        self.tokens.append(f"{tag}.{cls}" if cls else tag)


_RE_JSX_TAG = re.compile(r"<([A-Za-z][A-Za-z0-9.]*)((?:\"[^\"]*\"|'[^']*'|[^>\"'])*?)/?>")
_RE_CLASSNAME = re.compile(r"class(?:Name)?\s*=\s*[\"'{]([^\"'}]*)")


def skeleton_from_html(html: str) -> list[str]:
    s = _Skeleton()
    try:
        s.feed(html)
    except Exception:  # noqa: BLE001  (malformed markup must not break the gate)
        pass
    return s.tokens


def skeleton_from_jsx(src: str) -> list[str]:
    """Approximate skeleton of JSX source. Lossy by nature (a custom component is
    not the tag it renders), which is why this layer is a similarity score, not a
    pass/fail assertion."""
    out: list[str] = []
    for m in _RE_JSX_TAG.finditer(src):
        tag = m.group(1).lower()
        cm = _RE_CLASSNAME.search(m.group(2) or "")
        cls = " ".join(sorted((cm.group(1) if cm else "").split()))
        out.append(f"{tag}.{cls}" if cls else tag)
    return out


def structure_score(ref: list[str], clone: list[str]) -> Optional[float]:
    """Sequence similarity of two skeletons (None when either side is empty)."""
    if not ref or not clone:
        return None
    return difflib.SequenceMatcher(None, ref, clone).ratio()


def token_coverage(ref: dict[str, list[str]], clone: dict[str, list[str]]) -> Optional[float]:
    """Fraction of the reference's colors+fonts that appear in the clone (None when
    the reference has no tokens to compare)."""
    wanted: list[str] = []
    for key in ("colors", "fonts"):
        wanted += [t.strip().lower() for t in ref.get(key, []) if t.strip()]
    if not wanted:
        return None
    have = {t.strip().lower() for key in ("colors", "fonts")
            for t in clone.get(key, [])}
    hits = sum(1 for w in wanted if w in have)
    return hits / len(wanted)


def missing_tokens(ref: dict[str, list[str]], clone: dict[str, list[str]],
                   *, cap: int = 12) -> dict[str, list[str]]:
    """Reference colors/fonts absent from the clone — the actionable half of
    `token_coverage`, so feedback can name what to add instead of only a score."""
    out: dict[str, list[str]] = {}
    for key in ("colors", "fonts"):
        have = {t.strip().lower() for t in clone.get(key, [])}
        gone = [t for t in ref.get(key, [])
                if t.strip() and t.strip().lower() not in have]
        if gone:
            out[key] = gone[:cap]
    return out


def has_reference_ui(name: str, *, root: Optional[Path] = None) -> bool:
    """Did this app's build have a captured reference UI to reproduce? True only for a
    Flow-B clone whose capture succeeded — the one case where "does it look like the
    original" is a question with a ground truth."""
    base = Path(root) if root else WORKSPACE
    ev = _read_manifest(base / "specs" / name / "_ui")
    return bool(ev and ev.get("captured"))


# TWO DIFFERENT FLOORS, two different jobs — do not conflate them:
#
#   DEFAULT_MIN_SIMILARITY (0.75) is the GATE's fidelity floor: "is this clone close
#   enough to ship?" It sits in the wide empty gap measured between an identical app
#   (1.00) and an unrelated one (0.19-0.28), and it is advisory until a visual.yaml is
#   committed.
#
#   UI_ORACLE_FLOOR (0.45) is what the BUILD LOOP converges on, and it answers a much
#   weaker question: "did the builder use the vendored reference UI at all?" It is set
#   from the same measurements — comfortably above the 0.19-0.28 band an app that
#   ignored the reference scores, and deliberately well below a fidelity demand,
#   because no real clone attempt has been measured yet. Raise it once one has.
UI_ORACLE_FLOOR = 0.45


def combine(scores: dict[str, Optional[float]]) -> Optional[float]:
    """Weighted mean over the layers that actually produced a score."""
    num = 0.0
    den = 0.0
    for layer, weight in _WEIGHTS.items():
        s = scores.get(layer)
        if s is not None:
            num += weight * s
            den += weight
    return (num / den) if den else None


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #
def load_threshold(name: str, *, strict: bool = False,
                   root: Optional[Path] = None) -> tuple[float, bool, dict[str, Any]]:
    """Return (min_similarity, blocking, raw). A committed specs/<name>/visual.yaml
    means the user asked for a real floor → blocking; otherwise the default,
    advisory unless --strict. (Mirrors area.verify.nfr.load_budget, but parsed with
    yaml.safe_load because visual.yaml may carry a `reference_url` string.)"""
    root = Path(root) if root else WORKSPACE
    p = root / "specs" / name / "visual.yaml"
    threshold = DEFAULT_MIN_SIMILARITY
    blocking = strict
    raw: dict[str, Any] = {}
    if p.exists():
        blocking = True
        try:
            loaded = yaml.safe_load(p.read_text()) or {}
            if isinstance(loaded, dict):
                raw = loaded
                val = loaded.get("min_similarity")
                if isinstance(val, (int, float)):
                    threshold = float(val)
        except Exception:  # noqa: BLE001  (a malformed file must not crash the gate)
            pass
    return threshold, blocking, raw


# --------------------------------------------------------------------------- #
# reading both sides
# --------------------------------------------------------------------------- #
def _as_str_list(v: Any) -> list[str]:
    return [str(x) for x in v] if isinstance(v, list) else []


def _as_token_map(v: Any) -> dict[str, list[str]]:
    if not isinstance(v, dict):
        return {}
    return {str(k): _as_str_list(val) for k, val in v.items()}


def _read_manifest(ui_dir: Path) -> Optional[dict[str, Any]]:
    """Read `_ui/manifest.yaml` as a plain dict.

    Deliberately NOT via area.spec.models.UiEvidence: importing that executes
    `area/spec/__init__.py` → `extract_spec` → `area.engine` → the OpenHands SDK
    (measured ~1.8s) just to read six fields out of AREA's own artifact, and it
    would couple a measurement to the spec/agent stack. Tolerant dict access is
    enough here; area.re.ui_capture owns writing (and validating) the manifest.
    """
    p = ui_dir / "manifest.yaml"
    if not p.exists():
        return None
    try:
        loaded = yaml.safe_load(p.read_text())
    except Exception:  # noqa: BLE001
        return None
    return loaded if isinstance(loaded, dict) else None


def _globs(root: Path, patterns: tuple[str, ...], cap: int = 40) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    for pat in patterns:
        for p in root.glob(pat):
            if (p.is_file() and p not in seen
                    and not any(part in _SKIP_DIRS
                                for part in p.relative_to(root).parts)):
                seen.add(p)
                found.append(p)
                if len(found) >= cap:
                    return found
    return found


def _read_all(paths: list[Path]) -> str:
    out: list[str] = []
    for p in paths:
        try:
            out.append(p.read_text(errors="ignore"))
        except OSError:
            continue
    return "\n".join(out)


def _reference_skeleton(ui_dir: Path, rendered: list[str]) -> list[str]:
    tokens: list[str] = []
    for rel in rendered:
        p = ui_dir / rel
        if not p.is_file():
            continue
        try:
            text = p.read_text(errors="ignore")
        except OSError:
            continue
        if p.suffix.lower() in (".html", ".htm"):
            tokens += skeleton_from_html(text)
        else:
            tokens += skeleton_from_jsx(text)
    return tokens


# --------------------------------------------------------------------------- #
# pixel layer (live-URL reference only, opt-in)
# --------------------------------------------------------------------------- #
def _have_node() -> bool:
    return shutil.which("node") is not None and shutil.which("npx") is not None


_CRASH_NOISE = ("at ", "triggerUncaughtException", "Node.js v", "^")


def _harness_error(output: str) -> str:
    """Pick the USEFUL line out of a harness failure.

    visual_diff.mjs's contract is to print `error:`/`hint:`/`missing dependency:`,
    so prefer those. If it crashed instead, a Node dump's LAST line is the useless
    `Node.js vXX.Y.Z` footer — which is exactly what a naive tail reported before.
    """
    lines = [ln.strip() for ln in (output or "").splitlines() if ln.strip()]
    for ln in lines:
        if ln.lower().startswith(("error:", "missing dependency:", "hint:")):
            return ln[:200]
    for ln in lines:
        if ln.startswith(_CRASH_NOISE) or not set(ln) - set("╔╗╚╝║═^ "):
            continue
        return ln[:200]
    return "unknown harness failure"


def _pixel_layer(app: Path, out_dir: Path, reference_url: str,
                 *, timeout: float = 240.0) -> tuple[Optional[float], str, Optional[str]]:
    """Screenshot the booted clone + the live reference and diff them.

    Returns (score, skip_reason, clone_html). Heavy and environment-dependent by
    nature, so every failure path degrades to (None, reason, None) instead of
    failing the gate.
    """
    if not reference_url:
        return None, "no live reference URL (repo/path reference cannot be booted)", None
    if not _have_node():
        return None, "node/npx not available", None
    if not _TEMPLATE_DIFF.is_file():
        return None, "visual_diff.mjs template missing", None

    from area.verify.perf import _start_server, _stop, _wait_ready

    started = _start_server(app, 120.0)
    if not started:
        return None, "clone would not boot (no start/dev script, or it crashed)", None
    proc, port, _script, srv_out = started
    clone_url = f"http://127.0.0.1:{port}/"
    try:
        if not _wait_ready(clone_url, 120.0):
            # Quote what the clone's own server printed: "never answered HTTP" is true
            # and useless, and the server usually says exactly what is wrong.
            tail = "".join(srv_out)[-500:].strip().replace("\n", " | ")
            why = "clone booted but never answered HTTP"
            return None, (f"{why} — it said: {tail}" if tail else why), None
        clone_html: Optional[str] = None
        try:
            import urllib.request

            with urllib.request.urlopen(clone_url, timeout=30.0) as r:
                clone_html = r.read(2_000_000).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            clone_html = None

        out_dir.mkdir(parents=True, exist_ok=True)
        script = out_dir / "visual_diff.mjs"
        shutil.copy2(_TEMPLATE_DIFF, script)
        try:
            r = subprocess.run(
                ["node", str(script), clone_url, reference_url, str(out_dir)],
                cwd=str(app), capture_output=True, text=True, timeout=timeout,
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            return None, f"screenshot harness failed to run: {type(e).__name__}", clone_html
        if r.returncode != 0:
            why = _harness_error(f"{r.stderr or ''}\n{r.stdout or ''}")
            return None, f"screenshot harness error: {why}", clone_html
        res_path = out_dir / "pixel.json"
        if not res_path.is_file():
            return None, "screenshot harness produced no pixel.json", clone_html
        try:
            data = json.loads(res_path.read_text())
            mismatch = float(data["mismatch"])
        except Exception:  # noqa: BLE001
            return None, "pixel.json unreadable", clone_html
        return max(0.0, 1.0 - mismatch), "", clone_html
    finally:
        _stop(proc)


# --------------------------------------------------------------------------- #
# measurement + gate
# --------------------------------------------------------------------------- #
def measure(name: str, *, root: Optional[Path] = None,
            pixel: bool = False) -> dict[str, Any]:
    """Score the clone's look against the captured reference. Never raises for a
    missing/partial reference — the caller decides what an unmeasurable gate means."""
    root = Path(root) if root else WORKSPACE
    app = root / "apps" / name
    ui_dir = root / "specs" / name / "_ui"
    out_dir = app / VISUAL_DIR
    scores: dict[str, Optional[float]] = {"tokens": None, "dom": None, "pixel": None}
    skips: dict[str, str] = {}

    ev = _read_manifest(ui_dir)
    if ev is None or not ev.get("captured"):
        return {"scores": scores, "skips": {"all": "no reference UI captured at "
                                            f"{ui_dir} (clone built before part A?)"},
                "combined": None, "source_kind": "", "artifacts": str(out_dir)}

    # --- pixel first: it may yield the clone's RENDERED html for the dom layer ---
    clone_html: Optional[str] = None
    ref_url = str(ev.get("reference_url") or "")
    if pixel:
        scores["pixel"], why, clone_html = _pixel_layer(app, out_dir, ref_url)
        if why:
            skips["pixel"] = why
    else:
        skips["pixel"] = ("not enabled (pass --visual-pixel / set `pixel: true` in "
                          "visual.yaml; needs a live-URL reference + chromium)")

    # --- tokens ---
    ref_tokens = _as_token_map(ev.get("tokens"))
    clone_css = _read_all(_globs(app, _CLONE_CSS_GLOBS))
    gone: dict[str, list[str]] = {}
    if not clone_css.strip():
        skips["tokens"] = "no stylesheet found in the clone"
        gone = missing_tokens(ref_tokens, {})
    else:
        clone_tokens = extract_tokens(clone_css)
        cov = token_coverage(ref_tokens, clone_tokens)
        scores["tokens"] = cov
        gone = missing_tokens(ref_tokens, clone_tokens)
        if cov is None:
            skips["tokens"] = "reference captured no color/font tokens"

    # --- dom ---
    ref_skel = _reference_skeleton(ui_dir, _as_str_list(ev.get("rendered")))
    if clone_html:
        clone_skel = skeleton_from_html(clone_html)
    else:
        clone_skel = skeleton_from_jsx(_read_all(_globs(app, _CLONE_MARKUP_GLOBS)))
    s = structure_score(ref_skel, clone_skel)
    scores["dom"] = s
    if s is None:
        skips["dom"] = ("no comparable markup (reference or clone markup missing)"
                        if not ref_skel or not clone_skel else "")

    return {"scores": scores, "skips": skips, "combined": combine(scores),
            # the actionable half: WHICH reference tokens the clone is missing, so a
            # caller can tell a builder what to add instead of only showing a score
            "missing_tokens": gone,
            "source_kind": str(ev.get("source_kind") or ""), "reference_url": ref_url,
            "spa_caveat": bool(ev.get("spa_caveat")), "artifacts": str(out_dir)}


def visual_verify(name: str, *, backend: str = "acp", model: Optional[str] = None,
                  strict: bool = False, pixel: bool = False,
                  root: Optional[Path] = None) -> bool:
    """Grade the clone's visual parity against the captured reference UI.

    Returns True on pass, on an ADVISORY breach, or when nothing is measurable and
    no threshold was committed. backend/model are accepted for gate-dispatch
    uniformity but unused — the gate is deterministic.
    """
    name = safe_name(name)
    root = Path(root) if root else WORKSPACE
    app = root / "apps" / name
    if not app.exists():
        raise RuntimeError(f"no app at {app}")

    threshold, blocking, raw = load_threshold(name, strict=strict, root=root)
    if raw.get("pixel") is True:
        pixel = True
    res = measure(name, root=root, pixel=pixel)
    combined = res["combined"]

    out_dir = app / VISUAL_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "score.json").write_text(
        json.dumps({**res, "threshold": threshold, "blocking": blocking},
                   indent=2, default=str),
        encoding="utf-8",
    )

    for layer in ("pixel", "dom", "tokens"):
        s = res["scores"].get(layer)
        if s is None:
            why = res["skips"].get(layer) or res["skips"].get("all") or "unavailable"
            print(f"[area] visual {layer}: skipped — {why}")
        else:
            print(f"[area] visual {layer}: {s:.2f}")
    if res.get("spa_caveat"):
        print("[area] visual: ⚠ reference is a client-rendered SPA — captured "
              "markup/tokens are partial, so these scores read low by construction")

    if combined is None:
        # A committed threshold we could NOT measure must not silently pass.
        if blocking:
            print("[area] visual: FAIL — a visual floor is committed "
                  f"(specs/{name}/visual.yaml) but nothing was measurable")
            return False
        print("[area] visual: no measurable layer — skipped "
              f"(artifacts: {out_dir})")
        return True

    print(f"[area] visual: {combined:.2f} / {threshold:.2f} "
          f"(artifacts: {out_dir})")
    if combined >= threshold:
        print("[area] visual: PASS")
        return True
    if blocking:
        print(f"[area] visual: FAIL — {combined:.2f} below the committed floor "
              f"{threshold:.2f}")
        return False
    print(f"[area] visual: below {threshold:.2f} (ADVISORY — commit "
          f"specs/{name}/visual.yaml or pass --strict to make this block)")
    return True
