"""area.re.ui_capture — the deterministic Flow-B UI evidence capture.

Pure logic only: the SSRF guard (IP literals / localhost — no DNS, offline),
token extraction, the HTML asset collector, and the repo/_sample copy path on a
fake tree. No live agent, no network, no npm.
"""
import json

import yaml

from area.re.ui_capture import (
    _AssetCollector,
    capture_ui_evidence,
    is_safe_http_url,
)
from area.spec.models import Spec, UiEvidence
from area.ui_tokens import extract_tokens


# ---- SSRF guard (IP literals + localhost resolve locally → no network) ----------
def test_ssrf_guard_rejects_internal_and_bad_schemes():
    assert is_safe_http_url("http://127.0.0.1/") is False        # loopback
    assert is_safe_http_url("http://localhost/") is False        # → loopback
    assert is_safe_http_url("http://169.254.169.254/") is False  # cloud metadata
    assert is_safe_http_url("http://10.0.0.5/") is False         # private
    assert is_safe_http_url("http://[::1]/") is False            # loopback v6
    assert is_safe_http_url("file:///etc/passwd") is False       # scheme
    assert is_safe_http_url("ftp://8.8.8.8/") is False           # scheme
    assert is_safe_http_url("not a url") is False


def test_ssrf_guard_allows_public():
    assert is_safe_http_url("http://8.8.8.8/") is True
    assert is_safe_http_url("https://93.184.216.34/some/path") is True


# ---- token extraction -----------------------------------------------------------
def test_extract_tokens_colors_fonts_vars():
    css = """
    :root { --brand: #1e293b; --gap: 8px; }
    body { color: #FFF; background: rgb(10, 20, 30); font-family: 'Inter', sans-serif; }
    .x { border-color: hsl(200, 50%, 40%); }
    """
    t = extract_tokens(css)
    assert "#1e293b" in t["colors"] and "#fff" in t["colors"]
    assert any(c.startswith("rgb(") for c in t["colors"])
    assert "Inter" in t["fonts"] and "sans-serif" in t["fonts"]
    assert any(v.startswith("--brand:") for v in t["vars"])


# ---- HTML asset collector -------------------------------------------------------
def test_asset_collector_links_styles_and_spa_signal():
    html = (
        '<html><head>'
        '<link rel="stylesheet" href="/app.css">'
        '<link rel="icon" href="/favicon.ico">'
        '<style>.a{color:#abc}</style>'
        '</head><body><div id="__next"></div>'
        '<img src="/logo.png"><script src="/bundle.js"></script></body></html>'
    )
    c = _AssetCollector()
    c.feed(html)
    assert c.stylesheets == ["/app.css"]
    assert "/favicon.ico" in c.assets and "/logo.png" in c.assets
    assert c.inline_styles and ".a{color:#abc}" in "".join(c.inline_styles)
    assert c.has_root_mount is True and c.scripts == 1
    assert c.visible_text < 200  # SPA-ish shell


# ---- repo/_sample copy path -----------------------------------------------------
def _fake_sample(root):
    s = root / "_sample"
    (s / "app" / "dashboard").mkdir(parents=True)
    (s / "public").mkdir(parents=True)
    (s / "node_modules" / "pkg").mkdir(parents=True)
    (s / "app" / "globals.css").write_text(
        ":root{--brand:#0ea5e9}body{font-family:Inter;color:#111}")
    (s / "tailwind.config.js").write_text("module.exports={theme:{}}")
    (s / "app" / "page.tsx").write_text("export default function Page(){return null}")
    (s / "app" / "dashboard" / "page.tsx").write_text("export default ()=>null")
    (s / "public" / "logo.svg").write_text("<svg/>")
    # must be SKIPPED:
    (s / "node_modules" / "pkg" / "junk.css").write_text("body{color:red}")
    return s


def test_capture_from_sample(tmp_path):
    _fake_sample(tmp_path)
    ev = capture_ui_evidence("git@github.com:acme/app.git", "repo", tmp_path)

    assert ev.captured is True and ev.source_kind == "repo"
    assert any(p.endswith("globals.css") for p in ev.styles)
    assert any("tailwind.config.js" in p for p in ev.styles)
    assert not any("node_modules" in p for p in ev.styles)  # skip dir honored
    assert any(p.endswith("logo.svg") for p in ev.assets)
    assert len(ev.rendered) == 2  # app/page.tsx + app/dashboard/page.tsx
    assert all(p.startswith(("styles/", "assets/", "rendered/")) for p in
               ev.styles + ev.assets + ev.rendered)
    assert "#0ea5e9" in ev.tokens["colors"] and "Inter" in ev.tokens["fonts"]

    ui = tmp_path / "_ui"
    assert (ui / "manifest.yaml").exists()
    assert json.loads((ui / "tokens.json").read_text())["colors"]
    # manifest round-trips back into a UiEvidence
    man = yaml.safe_load((ui / "manifest.yaml").read_text())
    assert UiEvidence.model_validate(man).captured is True


def test_capture_no_sample_non_http_is_empty(tmp_path):
    ev = capture_ui_evidence("./does-not-exist", "path", tmp_path)
    assert ev.captured is False and "not an http" in ev.notes


# ---- Spec carries ui optionally + build dump excludes it ------------------------
def test_spec_ui_optional_roundtrip_and_dump_exclude():
    # old spec.yaml without `ui:` still loads (back-compat)
    base = {"name": "x", "summary": "s",
            "features": [{"id": "f", "title": "t", "description": "d"}]}
    assert Spec.model_validate(base).ui is None

    with_ui = dict(base, ui={"captured": True, "styles": ["styles/a.css"]})
    spec = Spec.model_validate(with_ui)
    assert spec.ui is not None and spec.ui.styles == ["styles/a.css"]
    # the build prompt dump drops `ui` (vendored files are the channel)
    assert "ui" not in spec.model_dump(exclude={"ui"})
    assert "ui" in spec.model_dump()
