"""area.verify.visual — the visual-parity gate (part C).

Pure logic + the advisory/blocking decision table on a fake workspace. The pixel
layer is not exercised here (it needs a live reference + chromium); what IS pinned
is that it degrades to a recorded skip instead of failing the gate.
"""
import json

import area.verify.visual as V


# ---- skeletons ------------------------------------------------------------------
def test_skeleton_from_html_strips_text_keeps_tag_and_class():
    sk = V.skeleton_from_html('<div class="b a"><p>hello</p><img src="x"></div>')
    assert sk == ["div.a b", "p", "img"]  # classes sorted, text dropped


def test_skeleton_from_jsx_reads_classname():
    sk = V.skeleton_from_jsx('<main className="wrap x"><Button className="b"/></main>')
    assert sk == ["main.wrap x", "button.b"]


# ---- scores ---------------------------------------------------------------------
def test_structure_score_identical_and_empty():
    a = ["div.x", "p"]
    assert V.structure_score(a, list(a)) == 1.0
    assert V.structure_score(a, ["span"]) < 0.5
    assert V.structure_score([], a) is None
    assert V.structure_score(a, []) is None


def test_token_coverage():
    ref = {"colors": ["#111", "#222"], "fonts": ["Inter"]}
    assert V.token_coverage(ref, {"colors": ["#111", "#222"], "fonts": ["Inter"]}) == 1.0
    cov = V.token_coverage(ref, {"colors": ["#111"], "fonts": []})
    assert cov is not None and abs(cov - 1 / 3) < 1e-9
    assert V.token_coverage({}, {"colors": ["#111"]}) is None   # nothing to compare


def test_combine_weights_available_layers_only():
    assert V.combine({"pixel": None, "dom": None, "tokens": None}) is None
    assert V.combine({"pixel": 1.0, "dom": 1.0, "tokens": 1.0}) == 1.0
    # dom .3 + tokens .2 → (0.3*1 + 0.2*0) / 0.5 = 0.6
    got = V.combine({"pixel": None, "dom": 1.0, "tokens": 0.0})
    assert got is not None and abs(got - 0.6) < 1e-9


# ---- threshold config -----------------------------------------------------------
def test_load_threshold_default_is_advisory(tmp_path):
    (tmp_path / "specs" / "a").mkdir(parents=True)
    thr, blocking, raw = V.load_threshold("a", strict=False, root=tmp_path)
    assert thr == V.DEFAULT_MIN_SIMILARITY and blocking is False and raw == {}
    assert V.load_threshold("a", strict=True, root=tmp_path)[1] is True


def test_load_threshold_committed_yaml_blocks(tmp_path):
    d = tmp_path / "specs" / "a"
    d.mkdir(parents=True)
    (d / "visual.yaml").write_text("min_similarity: 0.9\nreference_url: https://x.test/\n")
    thr, blocking, raw = V.load_threshold("a", strict=False, root=tmp_path)
    assert thr == 0.9 and blocking is True
    assert raw["reference_url"] == "https://x.test/"   # string key survives


def test_load_threshold_malformed_yaml_falls_back(tmp_path):
    d = tmp_path / "specs" / "a"
    d.mkdir(parents=True)
    (d / "visual.yaml").write_text("min_similarity: [not-a-number\n")
    thr, blocking, _ = V.load_threshold("a", strict=False, root=tmp_path)
    assert thr == V.DEFAULT_MIN_SIMILARITY and blocking is True  # present → blocking


# ---- fake workspace -------------------------------------------------------------
_MARKUP = '<main className="wrap"><h1 className="t">Hi</h1></main>'


def _ws(tmp_path, *, markup=_MARKUP, css="body{color:#0ea5e9;font-family:Inter}",
        ref_markup=_MARKUP, ref_tokens=None, captured=True, ui=True):
    import yaml

    app = tmp_path / "apps" / "c"
    (app / "app").mkdir(parents=True)
    (app / "app" / "page.tsx").write_text(markup)
    (app / "app" / "globals.css").write_text(css)
    spec = tmp_path / "specs" / "c"
    spec.mkdir(parents=True)
    if ui:
        uid = spec / "_ui"
        (uid / "rendered").mkdir(parents=True)
        (uid / "rendered" / "page.tsx").write_text(ref_markup)
        ev = {"captured": captured, "source_kind": "repo", "reference_url": "",
              "rendered": ["rendered/page.tsx"], "styles": [], "assets": [],
              "tokens": ref_tokens if ref_tokens is not None
              else {"colors": ["#0ea5e9"], "fonts": ["Inter"]},
              "spa_caveat": False}
        (uid / "manifest.yaml").write_text(yaml.safe_dump(ev))
    return tmp_path


def test_measure_scores_both_offline_layers(tmp_path):
    root = _ws(tmp_path)
    res = V.measure("c", root=root, pixel=False)
    assert res["scores"]["dom"] == 1.0        # identical markup
    assert res["scores"]["tokens"] == 1.0     # all reference tokens present
    assert res["scores"]["pixel"] is None     # not enabled
    assert "not enabled" in res["skips"]["pixel"]
    assert res["combined"] == 1.0


def test_measure_without_captured_ui_is_unmeasurable(tmp_path):
    root = _ws(tmp_path, ui=False)
    res = V.measure("c", root=root)
    assert res["combined"] is None and "no reference UI captured" in res["skips"]["all"]


def test_measure_mismatched_clone_scores_low(tmp_path):
    root = _ws(tmp_path, markup="<section><table><tr><td>x</td></tr></table></section>",
               css="body{color:#ff0000;font-family:Comic Sans}")
    res = V.measure("c", root=root)
    assert res["scores"]["tokens"] == 0.0
    assert res["scores"]["dom"] is not None and res["scores"]["dom"] < 0.5
    assert res["combined"] is not None and res["combined"] < 0.5


# ---- the gate decision ----------------------------------------------------------
def test_visual_verify_passes_and_writes_artifacts(tmp_path):
    root = _ws(tmp_path)
    assert V.visual_verify("c", root=root) is True
    score = json.loads((root / "apps" / "c" / V.VISUAL_DIR / "score.json").read_text())
    assert score["combined"] == 1.0 and score["threshold"] == V.DEFAULT_MIN_SIMILARITY
    assert score["blocking"] is False


def test_visual_verify_low_score_is_advisory_by_default(tmp_path):
    root = _ws(tmp_path, markup="<section><table><tr><td>x</td></tr></table></section>",
               css="body{color:#ff0000}")
    assert V.visual_verify("c", root=root) is True        # advisory → does not block


def test_visual_verify_low_score_blocks_with_strict(tmp_path):
    root = _ws(tmp_path, markup="<section><table><tr><td>x</td></tr></table></section>",
               css="body{color:#ff0000}")
    assert V.visual_verify("c", root=root, strict=True) is False


def test_visual_verify_low_score_blocks_with_committed_yaml(tmp_path):
    root = _ws(tmp_path, markup="<section><table><tr><td>x</td></tr></table></section>",
               css="body{color:#ff0000}")
    (root / "specs" / "c" / "visual.yaml").write_text("min_similarity: 0.95\n")
    assert V.visual_verify("c", root=root) is False


def test_visual_verify_committed_but_unmeasurable_fails_loudly(tmp_path):
    """Mirrors area.verify.nfr: a committed floor we could not measure must not
    silently pass."""
    root = _ws(tmp_path, ui=False)
    (root / "specs" / "c" / "visual.yaml").write_text("min_similarity: 0.9\n")
    assert V.visual_verify("c", root=root) is False


def test_visual_verify_unmeasurable_without_commitment_skips(tmp_path):
    root = _ws(tmp_path, ui=False)
    assert V.visual_verify("c", root=root) is True        # nothing committed → skip


def test_visual_verify_pixel_layer_skips_without_live_reference(tmp_path):
    """repo/path reference → no URL to screenshot; the layer records a reason
    rather than failing the gate."""
    root = _ws(tmp_path)
    res = V.measure("c", root=root, pixel=True)
    assert res["scores"]["pixel"] is None
    assert "no live reference URL" in res["skips"]["pixel"]


def test_visual_verify_missing_app_raises(tmp_path):
    import pytest

    with pytest.raises(RuntimeError, match="no app at"):
        V.visual_verify("nope", root=tmp_path)
