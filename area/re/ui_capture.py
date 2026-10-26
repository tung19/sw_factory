"""area.re.ui_capture — Flow B: capture the reference app's UI as EVIDENCE.

The RE spec stage captures only FEATURES + DATA MODEL (framework-neutral), so the
clone's look used to be re-invented from prose. This deterministic, best-effort
step snapshots the reference's REAL UI — rendered markup, stylesheets, design
tokens, static assets — into `specs/<name>/_ui/`, so the build can VENDOR it
(parity) and a visual oracle can later grade the clone against it. No agent, keyless.

Safety (mirrors the clone's READ-not-RUN rule):
- repo / local-path reference → we only COPY from the already-cloned
  `specs/<name>/_sample/` tree. Never run it, never `npm install`.
- live URL → GET http(s) only, behind an SSRF guard (reject loopback / private /
  link-local / reserved hosts, incl. 169.254.169.254 metadata), and we refuse to
  FOLLOW a redirect to an unsafe host. Everything is size-capped.
Capture is non-fatal: any failure degrades to `captured=False`, never breaks the
clone.
"""
from __future__ import annotations

import ipaddress
import json
import shutil
import socket
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from http.client import HTTPMessage
from html.parser import HTMLParser
from pathlib import Path
from typing import IO, Optional

import yaml

from area.spec.models import UiEvidence
from area.ui_tokens import extract_tokens, merge_tokens

_UA = "area-ui-capture"
_TIMEOUT = 15.0
_MAX_DOC = 2_000_000       # 2 MB HTML cap
_MAX_ASSET = 5_000_000     # 5 MB per fetched asset / stylesheet
_MAX_ASSETS = 40           # cap number of fetched assets (url mode)
_MAX_FILES = 60            # cap copied files per category (sample mode)

_SKIP_DIRS = {"node_modules", ".git", ".next", "dist", "build", ".area", "out",
              "coverage", ".turbo", ".vercel"}
_CONFIG_NAMES = (
    "tailwind.config.js", "tailwind.config.ts", "tailwind.config.cjs",
    "tailwind.config.mjs", "postcss.config.js", "postcss.config.mjs",
    "postcss.config.cjs", "theme.css", "tokens.css",
)
_MARKUP_GLOBS = (
    "app/**/layout.tsx", "app/**/page.tsx", "app/**/page.jsx",
    "src/app/**/layout.tsx", "src/app/**/page.tsx",
    "pages/**/*.tsx", "pages/**/*.jsx",
    "index.html", "public/index.html",
)
_ASSET_SUFFIXES = {".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico",
                   ".woff", ".woff2", ".ttf", ".otf", ".avif"}


# --------------------------------------------------------------------------- #
# SSRF guard + safe fetch
# --------------------------------------------------------------------------- #
def is_safe_http_url(url: str) -> bool:
    """http/https only, and every address the host resolves to must be public
    (reject loopback / private / link-local / reserved / multicast). Blocks SSRF
    to internal services and the 169.254.169.254 cloud-metadata endpoint."""
    try:
        u = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    if u.scheme not in ("http", "https") or not u.hostname:
        return False
    port = u.port or (443 if u.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(u.hostname, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, OSError, ValueError):
        return False
    if not infos:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(str(info[4][0]))
        except ValueError:
            return False
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            return False
    return True


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse to follow a redirect whose target fails the SSRF guard."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> Optional[urllib.request.Request]:
        if not is_safe_http_url(newurl):
            return None  # None → urllib raises HTTPError and stops (no unsafe hop)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_SafeRedirectHandler())


def _http_get(url: str, *, max_bytes: int) -> Optional[bytes]:
    """Best-effort GET of a SAFE http(s) URL, size-capped. None on any failure."""
    if not is_safe_http_url(url):
        return None
    req = urllib.request.Request(url, headers={"User-Agent": _UA}, method="GET")
    try:
        with _OPENER.open(req, timeout=_TIMEOUT) as resp:
            data: bytes = resp.read(max_bytes)
            return data
    except (urllib.error.URLError, OSError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# HTML asset collector (stdlib parser, no bs4 dependency)
# --------------------------------------------------------------------------- #
# Tags whose text content is NOT page copy. Without this, an SPA shell's inline
# <script> bodies counted as "visible text" (found dogfooding: excalidraw.com has
# `<div id="root"></div>` + 6 inline scripts and still measured 2615 chars of
# "text", so spa_caveat never fired on the textbook case it exists for).
_NON_TEXT_TAGS = {"script", "noscript", "template"}


class _AssetCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.stylesheets: list[str] = []
        self.inline_styles: list[str] = []
        self.assets: list[str] = []
        self.visible_text = 0
        self.scripts = 0
        self.has_root_mount = False
        self._in_style = False
        self._quiet = 0  # depth inside _NON_TEXT_TAGS

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        d = {k: (v or "") for k, v in attrs}
        if tag == "link":
            rel = d.get("rel", "").lower()
            href = d.get("href", "")
            if href and "stylesheet" in rel:
                self.stylesheets.append(href)
            elif href and "icon" in rel:
                self.assets.append(href)
        elif tag == "style":
            self._in_style = True
        elif tag == "img":
            if d.get("src"):
                self.assets.append(d["src"])
        elif tag == "script":
            self.scripts += 1
            if d.get("src"):
                self.assets.append(d["src"])
        elif tag == "div" and d.get("id", "") in ("root", "__next", "app"):
            self.has_root_mount = True
        if tag in _NON_TEXT_TAGS:
            self._quiet += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self._in_style = False
        if tag in _NON_TEXT_TAGS:
            self._quiet = max(0, self._quiet - 1)  # clamp: malformed markup

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self.inline_styles.append(data)
        elif not self._quiet:
            self.visible_text += len(data.strip())


# --------------------------------------------------------------------------- #
# Public entry
# --------------------------------------------------------------------------- #
def _is_http(source: str) -> bool:
    return source.strip().lower().startswith(("http://", "https://"))


def _empty(reason: str) -> UiEvidence:
    return UiEvidence(captured=False, notes=reason[:300])


def capture_ui_evidence(source: str, kind: str, spec_dir: str | Path) -> UiEvidence:
    """Snapshot the reference app's UI into `spec_dir/_ui/`. Best-effort, non-fatal.

    If a `_sample/` tree exists (repo/path reference cloned by RE) we copy from it;
    otherwise, for a live http(s) `source`, we fetch the served page + its CSS/assets.
    """
    spec_dir = Path(spec_dir)
    ui_dir = spec_dir / "_ui"
    sample = spec_dir / "_sample"
    try:
        has_sample = sample.is_dir() and any(sample.iterdir())
        if has_sample:
            ev = _capture_from_sample(source, sample, ui_dir)
        elif _is_http(source):
            ev = _capture_from_url(source, ui_dir)
        else:
            return _empty("no _sample/ tree and source is not an http(s) URL")
    except Exception as e:  # best-effort: a capture bug must never break the clone
        return _empty(f"capture error: {type(e).__name__}: {e}")
    ev.dir = str(ui_dir)
    _write_manifest(ui_dir, ev)
    return ev


# --------------------------------------------------------------------------- #
# repo / local-path: copy from the cloned _sample tree (READ only)
# --------------------------------------------------------------------------- #
def _iter_files(root: Path) -> Iterator[Path]:
    for p in root.rglob("*"):
        if p.is_file() and not any(part in _SKIP_DIRS for part in p.relative_to(root).parts):
            yield p


def _copy_rel(src: Path, root: Path, dest_root: Path, subdir: str) -> str:
    rel = src.relative_to(root)
    flat = "__".join(rel.parts)
    dest = dest_root / subdir / flat
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return f"{subdir}/{flat}"


def _capture_from_sample(source: str, sample: Path, ui_dir: Path) -> UiEvidence:
    styles: list[str] = []
    assets: list[str] = []
    rendered: list[str] = []
    tokens: dict[str, list[str]] = {}
    files = list(_iter_files(sample))

    for p in files:
        if len(styles) >= _MAX_FILES:
            break
        if p.suffix.lower() == ".css" or p.name in _CONFIG_NAMES:
            styles.append(_copy_rel(p, sample, ui_dir, "styles"))
            if p.suffix.lower() == ".css":
                try:
                    merge_tokens(tokens, extract_tokens(p.read_text(errors="ignore")))
                except OSError:
                    pass

    for p in files:
        if len(assets) >= _MAX_FILES:
            break
        if p.suffix.lower() in _ASSET_SUFFIXES:
            assets.append(_copy_rel(p, sample, ui_dir, "assets"))

    seen_markup: set[Path] = set()
    for pat in _MARKUP_GLOBS:
        for p in sample.glob(pat):
            if (p.is_file() and p not in seen_markup
                    and not any(part in _SKIP_DIRS for part in p.parts)):
                seen_markup.add(p)
                if len(rendered) < _MAX_FILES:
                    rendered.append(_copy_rel(p, sample, ui_dir, "rendered"))

    captured = bool(styles or rendered or assets)
    return UiEvidence(
        captured=captured,
        source_kind=_repo_or_path(source),
        rendered=rendered, styles=styles, assets=assets, tokens=tokens,
        notes="" if captured else "no stylesheets/markup/assets found in _sample",
    )


def _repo_or_path(source: str) -> str:
    s = source.strip()
    if s.endswith(".git") or s.startswith("git@") or "://" in s:
        return "repo"
    return "path"


# --------------------------------------------------------------------------- #
# live URL: fetch served HTML + same-origin CSS/assets
# --------------------------------------------------------------------------- #
def _capture_from_url(source: str, ui_dir: Path) -> UiEvidence:
    raw = _http_get(source, max_bytes=_MAX_DOC)
    if raw is None:
        return _empty(f"could not fetch {source} (unsafe host or network error)")
    html = raw.decode("utf-8", errors="replace")
    (ui_dir / "rendered").mkdir(parents=True, exist_ok=True)
    (ui_dir / "rendered" / "index.html").write_text(html, encoding="utf-8")
    rendered = ["rendered/index.html"]

    parser = _AssetCollector()
    try:
        parser.feed(html)
    except Exception:
        pass

    tokens: dict[str, list[str]] = {}
    for block in parser.inline_styles:
        merge_tokens(tokens, extract_tokens(block))

    base = source
    base_netloc = urllib.parse.urlsplit(source).netloc
    styles: list[str] = []
    for i, href in enumerate(parser.stylesheets[:_MAX_ASSETS]):
        url = urllib.parse.urljoin(base, href)
        if urllib.parse.urlsplit(url).netloc != base_netloc:
            continue  # same-origin only
        data = _http_get(url, max_bytes=_MAX_ASSET)
        if data is None:
            continue
        name = f"sheet{i}.css"
        (ui_dir / "styles").mkdir(parents=True, exist_ok=True)
        (ui_dir / "styles" / name).write_bytes(data)
        styles.append(f"styles/{name}")
        merge_tokens(tokens, extract_tokens(data.decode("utf-8", errors="replace")))

    assets: list[str] = []
    for i, src in enumerate(parser.assets[:_MAX_ASSETS]):
        url = urllib.parse.urljoin(base, src)
        if urllib.parse.urlsplit(url).netloc != base_netloc:
            continue
        suffix = Path(urllib.parse.urlsplit(url).path).suffix.lower()
        if suffix not in _ASSET_SUFFIXES:
            continue
        data = _http_get(url, max_bytes=_MAX_ASSET)
        if data is None:
            continue
        name = f"asset{i}{suffix}"
        (ui_dir / "assets").mkdir(parents=True, exist_ok=True)
        (ui_dir / "assets" / name).write_bytes(data)
        assets.append(f"assets/{name}")

    # SPA heuristic: almost no server-rendered text but a JS mount point + scripts
    spa = parser.visible_text < 200 and parser.has_root_mount and parser.scripts > 0
    return UiEvidence(
        captured=True,
        source_kind="url",
        reference_url=source,
        rendered=rendered, styles=styles, assets=assets, tokens=tokens,
        spa_caveat=spa,
        notes=("plain fetch saw little server-rendered content — this looks like a "
               "client-rendered SPA, so captured markup/tokens are partial"
               if spa else ""),
    )


def _write_manifest(ui_dir: Path, ev: UiEvidence) -> None:
    ui_dir.mkdir(parents=True, exist_ok=True)
    (ui_dir / "manifest.yaml").write_text(
        yaml.safe_dump(ev.model_dump(), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    (ui_dir / "tokens.json").write_text(
        json.dumps(ev.tokens, indent=2, ensure_ascii=False), encoding="utf-8"
    )
