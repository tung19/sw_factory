"""SLSA-style build provenance: digest the app source, attest materials→gates→
product, and verify-before-deploy as a tamper blocker. Pure logic — no agents."""
import area.deploy as D
import area.deploy.vercel as V
import area.provenance as P


def _app(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "page.tsx").write_text("export default () => <div>hi</div>;")
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "x.ts").write_text("export const x = 1;")
    return tmp_path


# ---- digests -----------------------------------------------------------------

def test_artifact_digest_deterministic(tmp_path):
    _app(tmp_path)
    assert P.artifact_digest(tmp_path) == P.artifact_digest(tmp_path)
    assert P.artifact_digest(tmp_path).startswith("sha256:")


def test_artifact_digest_changes_on_edit(tmp_path):
    _app(tmp_path)
    before = P.artifact_digest(tmp_path)
    (tmp_path / "lib" / "x.ts").write_text("export const x = 2;")  # tamper
    assert P.artifact_digest(tmp_path) != before


def test_artifact_digest_excludes_build_dirs(tmp_path):
    _app(tmp_path)
    before = P.artifact_digest(tmp_path)
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "junk.js").write_text("x")
    (tmp_path / ".next").mkdir()
    (tmp_path / ".next" / "o").write_text("y")
    assert P.artifact_digest(tmp_path) == before  # ignored dirs don't change it


def test_spec_digest(tmp_path):
    (tmp_path / "spec.yaml").write_text("name: A")
    d1 = P.spec_digest(tmp_path)
    assert d1 and d1.startswith("sha256:")
    assert P.spec_digest(tmp_path / "nope") is None


# ---- write / read / verify ---------------------------------------------------

def test_write_and_verify_ok(tmp_path):
    _app(tmp_path)
    (tmp_path / "spec.yaml").write_text("name: A\nsummary: s")
    prov = P.write_provenance(tmp_path, name="a", target="plain",
                              gates={"audit": True, "e2e": True}, spec_dir=tmp_path)
    assert prov["product"]["artifactDigest"].startswith("sha256:")
    assert prov["materials"]["spec"].startswith("sha256:")
    assert (tmp_path / P.PROV_REL).exists()
    status, _ = P.verify_provenance(tmp_path)
    assert status == "ok"


def test_writing_provenance_does_not_change_digest(tmp_path):
    # .area/ is excluded, so the attestation file can't invalidate its own digest
    _app(tmp_path)
    before = P.artifact_digest(tmp_path)
    P.write_provenance(tmp_path, name="a", target="plain", gates={})
    assert P.artifact_digest(tmp_path) == before


def test_verify_mismatch_after_tamper(tmp_path):
    _app(tmp_path)
    P.write_provenance(tmp_path, name="a", target="plain", gates={"audit": True})
    (tmp_path / "app" / "page.tsx").write_text("export default () => <div>HACKED</div>;")
    status, detail = P.verify_provenance(tmp_path)
    assert status == "mismatch" and "CHANGED" in detail


def test_verify_absent(tmp_path):
    _app(tmp_path)
    status, _ = P.verify_provenance(tmp_path)
    assert status == "absent"


# ---- deploy gate integration -------------------------------------------------

def test_deploy_blocks_on_mismatch_when_required(monkeypatch, tmp_path):
    (tmp_path / "package.json").write_text('{"scripts":{"build":"next build"}}')
    _app(tmp_path)
    P.write_provenance(tmp_path, name="a", target="plain", gates={"audit": True})
    (tmp_path / "lib" / "x.ts").write_text("export const x = 999;")  # tamper after gating
    called = []
    monkeypatch.setattr(V, "deploy", lambda a: (called.append("v"), (True, "", None))[1])
    ok, url = D.deploy_with_gate(tmp_path, confirm=lambda p: True, require_provenance=True)
    assert ok is False and url is None and called == []  # refused, never deployed


def test_deploy_proceeds_on_ok_provenance(monkeypatch, tmp_path):
    (tmp_path / "package.json").write_text('{"scripts":{"build":"next build"}}')
    _app(tmp_path)
    P.write_provenance(tmp_path, name="a", target="plain", gates={"audit": True})
    monkeypatch.setattr(V, "deploy",
                        lambda a: (True, "", "https://x.vercel.app"))
    ok, url = D.deploy_with_gate(tmp_path, confirm=lambda p: True, require_provenance=True)
    assert ok and url == "https://x.vercel.app"


def test_deploy_absent_provenance_only_warns_by_default(monkeypatch, tmp_path):
    (tmp_path / "package.json").write_text('{"scripts":{"build":"next build"}}')
    _app(tmp_path)  # no provenance written
    monkeypatch.setattr(V, "deploy", lambda a: (True, "", "https://x.vercel.app"))
    ok, url = D.deploy_with_gate(tmp_path, confirm=lambda p: True)  # require=False
    assert ok and url == "https://x.vercel.app"  # absent -> warn, still deploys


# ---- round-5 #11: dir-name blind spot + materials completeness ----------------

def test_digest_skips_toplevel_build_but_keeps_nested_source(tmp_path):
    _app(tmp_path)
    base = P.artifact_digest(tmp_path)
    # a TOP-LEVEL build/ is a build output → excluded (digest unchanged)
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "out.js").write_text("compiled")
    assert P.artifact_digest(tmp_path) == base
    # ...but a legitimate NESTED source dir named build/ is now digested
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "build").mkdir()
    (tmp_path / "src" / "build" / "helpers.ts").write_text("export const h = 1;")
    assert P.artifact_digest(tmp_path) != base  # nested source counted (was a blind spot)


def test_digest_skips_nested_node_modules(tmp_path):
    _app(tmp_path)
    base = P.artifact_digest(tmp_path)
    nm = tmp_path / "vendor" / "braces" / "node_modules" / "fill-range"
    nm.mkdir(parents=True)
    (nm / "index.js").write_text("junk")
    assert P.artifact_digest(tmp_path) == base  # node_modules skipped at any depth


def test_spec_digest_covers_gate_budgets(tmp_path):
    sd = tmp_path / "specs" / "app"
    sd.mkdir(parents=True)
    (sd / "spec.yaml").write_text("name: app\n")
    (sd / "acceptance.yaml").write_text("criteria: []\n")
    base = P.spec_digest(sd)
    assert base and base.startswith("sha256:")
    # a committed gate budget is now part of the attested materials
    (sd / "cost.yaml").write_text("max_usd: 5\n")
    assert P.spec_digest(sd) != base
    (sd / "nfr.yaml").write_text("bundle_kib: 100\n")
    assert P.spec_digest(sd) != P.spec_digest(sd.parent / "nonexistent")  # sanity


def test_spec_digest_none_when_empty(tmp_path):
    sd = tmp_path / "specs" / "empty"
    sd.mkdir(parents=True)
    assert P.spec_digest(sd) is None
