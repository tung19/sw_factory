"""The attestation must describe the bytes that actually ship.

Last remaining item of the 4-dimension source audit (#11). `verify_provenance` ran in
`deploy_with_gate`, but `harden_cf_app` — the deterministic vinext safety net: pin the
compat date, write npm overrides, vendor patched braces — ran afterwards, INSIDE
`cloudflare.deploy()`. So the attestation said "this is what was gated" about the
pre-hardened source while the mutated bytes deployed.

Two halves, both tested here:
  * `_finish` hardens a cloudflare app BEFORE the gates, so the gated (and attested)
    state is already the shipping state;
  * `deploy_with_gate` hardens again as a TRIPWIRE and refuses if anything changed.

Agent-free: no npm, no network, no wrangler.
"""
import argparse
import types
from pathlib import Path

import area.cli as C
import area.deploy as D
import area.deploy.cloudflare as CF


def _cf_app(tmp_path: Path) -> Path:
    (tmp_path / "cloudflare.config.ts").write_text("env: { DB: bindings.d1() }\n")
    (tmp_path / "package.json").write_text('{"scripts":{"build:cf":"vite build"}}')
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "page.tsx").write_text("export default () => null;\n")
    return tmp_path


# ---- the tripwire -------------------------------------------------------------
def test_a_no_op_safety_net_lets_the_deploy_through(tmp_path, monkeypatch):
    app = _cf_app(tmp_path)
    monkeypatch.setattr("area.build.cf_scaffold.harden_cf_app", lambda a, **k: {})
    assert D._settle_before_attesting(str(app), "cloudflare") is True


def test_a_mutating_safety_net_refuses_the_deploy(tmp_path, monkeypatch, capsys):
    """If cf-fix HAD to change an already-gated app, the gates judged other bytes."""
    app = _cf_app(tmp_path)

    def mutate(a, **k):
        (Path(a) / "package.json").write_text(
            '{"scripts":{"build:cf":"vite build"},"overrides":{"braces":"file:./v"}}')
        return {"cve_overrides": True}

    monkeypatch.setattr("area.build.cf_scaffold.harden_cf_app", mutate)
    assert D._settle_before_attesting(str(app), "cloudflare") is False
    out = capsys.readouterr().out
    assert "already gated" in out and "area cf-fix" in out


def test_the_tripwire_catches_a_change_it_was_not_told_about(tmp_path, monkeypatch):
    """Deliberately broader than harden_cf_app's own three-flag summary: the digest
    comparison catches ANY source change, even one the net does not report."""
    app = _cf_app(tmp_path)

    def sneaky(a, **k):
        (Path(a) / "app" / "page.tsx").write_text("export default () => 'changed';\n")
        return {}  # reports nothing changed

    monkeypatch.setattr("area.build.cf_scaffold.harden_cf_app", sneaky)
    assert D._settle_before_attesting(str(app), "cloudflare") is False


def test_non_cloudflare_is_untouched(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr("area.build.cf_scaffold.harden_cf_app",
                        lambda a, **k: called.append(1))
    assert D._settle_before_attesting(str(tmp_path), "vercel") is True
    assert called == []


def test_a_broken_safety_net_does_not_block(tmp_path, monkeypatch, capsys):
    """The net is a diagnostic, not a gate: if it cannot run, say so and continue —
    `verify_provenance` is still the thing that must hold."""
    app = _cf_app(tmp_path)

    def boom(a, **k):
        raise RuntimeError("npm missing")

    monkeypatch.setattr("area.build.cf_scaffold.harden_cf_app", boom)
    assert D._settle_before_attesting(str(app), "cloudflare") is True
    assert "skipped (warn)" in capsys.readouterr().out


def test_deploy_runs_the_tripwire_before_verifying_provenance(tmp_path, monkeypatch):
    """Ordering is the whole point. If the tripwire refuses, provenance must not even
    be consulted — and nothing may deploy."""
    app = _cf_app(tmp_path)
    order: list[str] = []
    monkeypatch.setattr(D, "_settle_before_attesting",
                        lambda a, p: (order.append("settle"), False)[1])
    monkeypatch.setattr("area.provenance.verify_provenance",
                        lambda a: (order.append("verify"), ("ok", ""))[1])
    monkeypatch.setattr(CF, "deploy",
                        lambda a: (order.append("deploy"), (True, "", None))[1])
    ok, url = D.deploy_with_gate(app, confirm=lambda p: True)
    assert ok is False and url is None
    assert order == ["settle"], f"nothing may run after a refused tripwire: {order}"


def test_cloudflare_deploy_no_longer_mutates_the_app():
    """The mutation must not sneak back into the deploy call itself."""
    import inspect

    assert "harden_cf_app" not in inspect.getsource(CF.deploy)


# ---- the other half: gated state == shipping state ---------------------------
def test_finish_hardens_a_cloudflare_app_before_the_gates(tmp_path, monkeypatch):
    """So the gates judge — and provenance attests — what will actually deploy."""
    order: list[str] = []
    monkeypatch.setattr("area.build.cf_scaffold.harden_cf_app",
                        lambda a, **k: order.append("harden"))
    monkeypatch.setattr(C, "_run_gate",
                        lambda g, n, a: (order.append(f"gate:{g}"), True)[1])
    monkeypatch.setattr(C, "_factory_verify", lambda a: True)
    res = types.SimpleNamespace(passed=True, name="t", spec_dir=tmp_path,
                                app_dir=tmp_path, clarify_needed=False)
    args = argparse.Namespace(target="cloudflare", audit=True, deploy=False,
                              all=False, tdd=False, open=False, no_e2e=True)
    C._finish(res, args)
    assert order and order[0] == "harden", f"hardening must precede the gates: {order}"
    assert "gate:audit" in order


def test_finish_skips_hardening_for_a_non_cloudflare_target(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr("area.build.cf_scaffold.harden_cf_app",
                        lambda a, **k: called.append(1))
    monkeypatch.setattr(C, "_run_gate", lambda g, n, a: True)
    monkeypatch.setattr(C, "_factory_verify", lambda a: True)
    res = types.SimpleNamespace(passed=True, name="t", spec_dir=tmp_path,
                                app_dir=tmp_path, clarify_needed=False)
    args = argparse.Namespace(target="plain", audit=True, deploy=False, all=False,
                              tdd=False, open=False, no_e2e=True)
    C._finish(res, args)
    assert called == []
