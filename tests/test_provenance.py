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


def test_deploy_absent_provenance_refuses_by_default(monkeypatch, tmp_path):
    """Policy change (secure-factory assessment, group 2): an artifact AREA's gates
    never attested does NOT ship by default. It used to warn and deploy."""
    (tmp_path / "package.json").write_text('{"scripts":{"build":"next build"}}')
    _app(tmp_path)  # no provenance written
    called = []
    monkeypatch.setattr(V, "deploy",
                        lambda a: (called.append("v"), (True, "", "https://x"))[1])
    ok, url = D.deploy_with_gate(tmp_path, confirm=lambda p: True)
    assert ok is False and url is None and called == []


def test_deploy_absent_provenance_ships_on_explicit_opt_out(monkeypatch, tmp_path):
    """The escape hatch stays, but it has to be asked for."""
    (tmp_path / "package.json").write_text('{"scripts":{"build":"next build"}}')
    _app(tmp_path)
    monkeypatch.setattr(V, "deploy", lambda a: (True, "", "https://x.vercel.app"))
    ok, url = D.deploy_with_gate(tmp_path, confirm=lambda p: True,
                                 require_provenance=False)
    assert ok and url == "https://x.vercel.app"


def test_env_can_opt_out_of_requiring_provenance(monkeypatch, tmp_path):
    """AREA_REQUIRE_PROVENANCE was dead code: `--require-provenance` is a store_true,
    so the CLI passed False explicitly and the `is None` branch never ran."""
    (tmp_path / "package.json").write_text('{"scripts":{"build":"next build"}}')
    _app(tmp_path)
    monkeypatch.setenv("AREA_REQUIRE_PROVENANCE", "0")
    monkeypatch.setattr(V, "deploy", lambda a: (True, "", "https://x.vercel.app"))
    ok, _ = D.deploy_with_gate(tmp_path, confirm=lambda p: True)  # None -> ask the env
    assert ok


def test_deploy_refuses_when_the_checker_cannot_run(monkeypatch, tmp_path):
    """Fail-CLOSED: the provenance check used to swallow its own exception and deploy
    anyway, so the one enforcement point before production failed open."""
    (tmp_path / "package.json").write_text('{"scripts":{"build":"next build"}}')
    _app(tmp_path)
    P.write_provenance(tmp_path, name="a", target="plain", gates={"audit": True})
    called = []
    monkeypatch.setattr(V, "deploy",
                        lambda a: (called.append("v"), (True, "", "https://x"))[1])

    def _boom(_app_dir):
        raise RuntimeError("checker exploded")

    monkeypatch.setattr(P, "verify_provenance", _boom)
    ok, url = D.deploy_with_gate(tmp_path, confirm=lambda p: True)
    assert ok is False and url is None and called == []


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


# ---- attestation honesty (secure-factory assessment, group 1) -----------------

def test_builder_names_the_real_backend(tmp_path):
    """`builder` defaulted to the literal "area/openhands-acp" and the CLI never
    overrode it, so every attestation claimed ACP — including `--backend llm` runs."""
    import argparse

    import area.cli as C

    assert C._builder_id(argparse.Namespace(backend="llm")) == "area/llm"
    assert C._builder_id(argparse.Namespace(backend="acp")) == "area/acp"
    assert C._builder_id(argparse.Namespace()) == "area/acp"  # default, not a lie
    _app(tmp_path)
    prov = P.write_provenance(tmp_path, name="a", target="plain", gates={},
                              builder="area/llm")
    assert prov["builder"] == "area/llm"
    # and no silently-wrong default when a caller forgets
    assert P.write_provenance(tmp_path, name="a", target="plain",
                              gates={})["builder"] == "area/unknown"


def test_policy_block_records_how_the_build_was_configured(tmp_path):
    import argparse

    import area.cli as C

    args = argparse.Namespace(backend="llm", model="m-1", strict=True, tdd=True,
                              audit_level="critical", no_block_injection=False,
                              budget=7.5, agent_iters=40, spec_iters=2, build_iters=5)
    pol = C._run_policy(args)
    assert pol["backend"] == "llm" and pol["model"] == "m-1"
    assert pol["strict"] is True and pol["blockInjection"] is True
    assert pol["budgetUsd"] == 7.5 and pol["agentIters"] == 40

    _app(tmp_path)
    prov = P.write_provenance(tmp_path, name="a", target="plain", gates={}, policy=pol)
    # the factory's OWN revision + skills pack are filled in automatically — without
    # them a past build cannot be reconstructed (the gates live in AREA, not the app)
    assert prov["policy"]["factoryCommit"]
    assert prov["policy"]["skillsDigest"].startswith("sha256:")
    assert prov["policy"]["model"] == "m-1"


def test_advisory_gate_is_not_recorded_as_a_pass(tmp_path):
    """`{g: True for g in gates}` recorded SELECTION, not outcome: an advisory gate
    below its threshold was attested identically to an enforced pass."""
    _app(tmp_path)
    prov = P.write_provenance(
        tmp_path, name="a", target="plain",
        gates={"audit": {"ran": True, "blocking": True, "blocked": False},
               "visual": {"ran": True, "blocking": False, "blocked": False}},
        gates_not_run=["chaos", "perf"])
    enforced, advisory = P._gate_summary(prov["gates"])
    assert enforced == ["audit"] and advisory == ["visual"]
    assert prov["gatesNotRun"] == ["chaos", "perf"]
    status, detail = P.verify_provenance(tmp_path)
    assert status == "ok"
    assert "gates enforced: audit" in detail
    assert "advisory ONLY (not a pass): visual" in detail
    assert "not run: chaos, perf" in detail


def test_gate_summary_treats_unknown_posture_conservatively(tmp_path):
    """A posture the CLI could not determine is recorded as null. The summary must
    not then claim the gate was enforced."""
    enforced, advisory = P._gate_summary(
        {"cost": {"ran": True, "blocking": None, "blocked": False}})
    assert enforced == [] and advisory == ["cost"]
    # a gate that never ran is in neither bucket
    assert P._gate_summary({"perf": {"ran": False}}) == ([], [])


def test_gate_summary_still_reads_a_v1_record():
    """v1 wrote bare bools and could not express an advisory pass; read them as
    enforced rather than silently downgrading old attestations."""
    assert P._gate_summary({"audit": True, "e2e": False}) == (["audit"], [])


def test_gate_blocking_asks_each_gate_s_own_loader(tmp_path, monkeypatch):
    import argparse

    import area.cli as C

    args = argparse.Namespace(strict=False, cost_max=None)
    # oracle/tier-1 gates always block
    for g in ("verify", "audit", "e2e", "chaos"):
        assert C._gate_blocking(g, "app", args) is True
    # the LLM reviewer only blocks under --strict
    assert C._gate_blocking("product", "app", args) is False
    assert C._gate_blocking("product", "app", argparse.Namespace(
        strict=True, cost_max=None)) is True
    # a committed budget flips a budget gate to blocking — ask the real loader
    (tmp_path / "specs" / "app").mkdir(parents=True)
    monkeypatch.setattr("area.verify.nfr.WORKSPACE", tmp_path)
    assert C._gate_blocking("nfr", "app", args) is False
    (tmp_path / "specs" / "app" / "nfr.yaml").write_text("bundle_kb: 100\n")
    assert C._gate_blocking("nfr", "app", args) is True


def test_gate_blocking_records_unknown_instead_of_guessing(monkeypatch):
    import argparse

    import area.cli as C

    def _boom(*a, **k):
        raise RuntimeError("loader broken")

    monkeypatch.setattr("area.verify.visual.load_threshold", _boom)
    assert C._gate_blocking("visual", "app", argparse.Namespace(
        strict=False, cost_max=None)) is None
