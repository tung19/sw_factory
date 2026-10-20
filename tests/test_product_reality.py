"""Product-fit gate (#3), design-auto for non-trivial apps (#3b), reality loop (#4).

Pure logic + injected fakes — no real agents."""
import types

import area.design
import area.pipeline as P
import area.verify.product as PV
from area.reality import build_reality_report


# ---------- product _parse_verdict (pure) ----------
def test_parse_verdict_ok_and_concerns():
    ok = PV._parse_verdict(f"{PV.SENTINEL}\nverdict: ok\ncoverage: 3/3\ngaps: []\n")
    assert ok["verdict"] == "ok" and ok["coverage"] == "3/3" and ok["gaps"] == []
    c = PV._parse_verdict(
        f"{PV.SENTINEL}\nverdict: concerns\ncoverage: 1/3\ngaps:\n  - no UI for export\n")
    assert c["verdict"] == "concerns" and "no UI for export" in c["gaps"]


def test_parse_verdict_junk_defaults_ok():
    assert PV._parse_verdict("total garbage")["verdict"] == "ok"
    assert PV._parse_verdict("")["verdict"] == "ok"


# ---------- product_verify: advisory by default, blocks only with --strict ----------
def _mk(root, name="app"):
    sd = root / "specs" / name
    sd.mkdir(parents=True)
    (sd / "spec.yaml").write_text("name: x\nfeatures: []\n")
    (sd / "acceptance.yaml").write_text("criteria: []\n")
    (root / "apps" / name).mkdir(parents=True)


def test_product_advisory_passes_on_concerns(tmp_path):
    _mk(tmp_path)
    ask = lambda _p: f"{PV.SENTINEL}\nverdict: concerns\ncoverage: 1/3\ngaps:\n  - dead feature\n"
    assert PV.product_verify("app", root=tmp_path, ask=ask) is True  # advisory → pass


def test_product_strict_blocks_on_concerns(tmp_path):
    _mk(tmp_path)
    ask = lambda _p: f"{PV.SENTINEL}\nverdict: concerns\ncoverage: 1/3\ngaps: [x]\n"
    assert PV.product_verify("app", root=tmp_path, strict=True, ask=ask) is False


def test_product_passes_when_ok(tmp_path):
    _mk(tmp_path)
    ask = lambda _p: f"{PV.SENTINEL}\nverdict: ok\ncoverage: 3/3\ngaps: []\n"
    assert PV.product_verify("app", root=tmp_path, strict=True, ask=ask) is True


def test_product_fail_open(tmp_path):
    _mk(tmp_path)

    def boom(_p):
        raise RuntimeError("no claude on PATH")

    assert PV.product_verify("app", root=tmp_path, strict=True, ask=boom) is True
    assert PV.product_verify("missing", root=tmp_path, strict=True, ask=boom) is True


# ---------- reality report (#4, pure) ----------
def test_reality_report_shows_material_assumptions(tmp_path):
    sd = tmp_path / "specs" / "app"
    sd.mkdir(parents=True)
    (sd / "assumptions.yaml").write_text(
        "assumptions:\n"
        '  - question: "who is the user?"\n'
        "    assumption: admin\n"
        "    material: true\n"
        '  - question: "a minor thing?"\n'
        "    assumption: x\n"
        "    material: false\n")
    rep = build_reality_report("app", sd, tmp_path / "apps" / "app")
    assert "who is the user?" in rep and "admin" in rep
    assert "a minor thing?" not in rep           # only MATERIAL shown
    assert 'area iterate app' in rep and "npm run dev" in rep


def test_reality_report_no_assumptions_and_deployed(tmp_path):
    sd = tmp_path / "specs" / "app"
    sd.mkdir(parents=True)
    rep = build_reality_report("app", sd, tmp_path / "apps" / "app",
                               deployed_url="https://app.example.dev")
    assert "no ambiguities" in rep and "https://app.example.dev" in rep


# ---------- design-auto (#3b) ----------
def test_should_design_heuristic():
    assert P._should_design(types.SimpleNamespace(features=[1, 2, 3], entities=[])) is True
    assert P._should_design(types.SimpleNamespace(features=[1], entities=[{"x": 1}])) is True
    assert P._should_design(types.SimpleNamespace(features=[1], entities=[])) is False


def _fake_pipeline(monkeypatch, spec):
    acc = types.SimpleNamespace(criteria=[1], model_dump=lambda: {})
    monkeypatch.setattr(P, "extract_spec", lambda req, out, **kw: (spec, acc))
    monkeypatch.setattr(P, "_build", lambda name, s, a, root, *a2, **k:
                        P.PipelineResult(name, s, a, root, root, True))
    ran = []
    # _maybe_design does `from area.design import design_stage`, so patch it there
    monkeypatch.setattr(area.design, "design_stage", lambda name, **kw: ran.append(name))
    return ran


def test_design_auto_runs_for_nontrivial(monkeypatch, tmp_path):
    spec = types.SimpleNamespace(features=[1, 2, 3], entities=[], model_dump=lambda: {})
    ran = _fake_pipeline(monkeypatch, spec)
    P.run_pipeline("x", name="app", clarify=False, workspace=tmp_path)  # design unset → auto
    assert ran == ["app"]


def test_design_auto_skips_trivial(monkeypatch, tmp_path):
    spec = types.SimpleNamespace(features=[1], entities=[], model_dump=lambda: {})
    ran = _fake_pipeline(monkeypatch, spec)
    P.run_pipeline("x", name="app", clarify=False, workspace=tmp_path)
    assert ran == []


def test_design_explicit_false_overrides_auto(monkeypatch, tmp_path):
    spec = types.SimpleNamespace(features=[1, 2, 3], entities=[], model_dump=lambda: {})
    ran = _fake_pipeline(monkeypatch, spec)
    P.run_pipeline("x", name="app", clarify=False, design=False, workspace=tmp_path)
    assert ran == []  # --no-design beats the non-trivial heuristic
