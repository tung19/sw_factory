"""area.build.cf_scaffold — the PR2 fuller fallback: vendoring the patched braces
(from the committed template), restoring it after a prune, cloning a known-good
sibling toolchain, and the build-with-fallback orchestration. All offline — the
real template is copied, npm/build are injected or not invoked."""
import json

import area.build.cf_scaffold as CF


# ---- vendor_braces (uses the real committed template) ---------------------------

def test_vendor_braces_materialises_deps(tmp_path):
    assert CF.vendor_braces(tmp_path) is True
    braces = tmp_path / "vendor" / "braces"
    assert (braces / "index.js").is_file()
    assert (braces / "lib" / "parse.js").is_file()
    # _deps is materialised into node_modules so the package is self-contained
    assert (braces / "node_modules" / "fill-range").is_dir()
    assert (braces / "node_modules" / "is-number").is_dir()
    # the depth-guard patch is present in the vendored source
    assert "maxDepth" in (braces / "lib" / "parse.js").read_text()


def test_vendor_braces_idempotent(tmp_path):
    CF.vendor_braces(tmp_path)
    assert CF.vendor_braces(tmp_path) is True  # re-vendor is clean, still True


# ---- restore_vendored_braces (the fill-range prune fix) -------------------------

def test_restore_after_prune(tmp_path):
    CF.vendor_braces(tmp_path)
    nm = tmp_path / "vendor" / "braces" / "node_modules"
    # simulate the parent `npm install` pruning braces' transitive deps
    import shutil
    shutil.rmtree(nm)
    assert CF.restore_vendored_braces(tmp_path) is True
    assert (nm / "fill-range").is_dir()


def test_restore_noop_when_intact(tmp_path):
    CF.vendor_braces(tmp_path)
    assert CF.restore_vendored_braces(tmp_path) is False  # node_modules intact


def test_restore_noop_when_not_vendored(tmp_path):
    assert CF.restore_vendored_braces(tmp_path) is False  # nothing vendored


# ---- clone_sibling_toolchain ----------------------------------------------------

def _sibling(tmp_path):
    sib = tmp_path / "sib"
    sib.mkdir()
    (sib / "package.json").write_text(json.dumps({"name": "sib", "scripts": {}}))
    (sib / "cloudflare.config.ts").write_text(
        'export default { name: "sib-worker", compatibilityDate: "2026-01-01" }')
    (sib / "vite.config.ts").write_text("export default {}")
    (sib / "next-env.d.ts").write_text("// next-env")
    (sib / "node_modules").mkdir()
    (sib / "node_modules" / "marker.txt").write_text("installed")
    (sib / "vendor").mkdir()
    (sib / "vendor" / "braces.txt").write_text("vendored")
    return sib


def test_clone_sibling_copies_and_renames(tmp_path):
    sib = _sibling(tmp_path)
    app = tmp_path / "myclone"
    copied = CF.clone_sibling_toolchain(app, sib)
    assert "package.json" in copied and "cloudflare.config.ts" in copied
    assert "node_modules/" in copied and "vendor/" in copied
    # toolchain reused
    assert (app / "node_modules" / "marker.txt").read_text() == "installed"
    assert (app / "vendor" / "braces.txt").is_file()
    # renamed to the new app
    assert json.loads((app / "package.json").read_text())["name"] == "myclone"
    assert 'name: "myclone"' in (app / "cloudflare.config.ts").read_text()


def test_clone_skips_absent_files(tmp_path):
    sib = tmp_path / "sib"
    sib.mkdir()
    (sib / "package.json").write_text(json.dumps({"name": "sib"}))
    copied = CF.clone_sibling_toolchain(tmp_path / "c", sib)
    assert copied == ["package.json"]  # only what existed


# ---- build_cf_with_fallback -----------------------------------------------------

def test_fallback_retries_with_sibling(tmp_path):
    sib = _sibling(tmp_path)
    app = tmp_path / "app"
    app.mkdir()
    (app / "package.json").write_text(json.dumps({"name": "app"}))
    calls = {"n": 0}

    def runner(a, script):
        calls["n"] += 1
        return (calls["n"] > 1, f"run#{calls['n']}")  # fail first, pass after clone

    ok, log = CF.build_cf_with_fallback(app, sibling=sib, runner=runner)
    assert ok is True and calls["n"] == 2
    assert "sibling-clone fallback" in log
    # the clone actually happened (sibling's node_modules is now in the app)
    assert (app / "node_modules" / "marker.txt").is_file()


def test_no_fallback_without_sibling(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    calls = {"n": 0}

    def runner(a, script):
        calls["n"] += 1
        return (False, "boom")

    ok, log = CF.build_cf_with_fallback(app, sibling=None, runner=runner)
    assert ok is False and calls["n"] == 1  # no retry


# ---- _is_cf_app / harden vendors for CF apps ------------------------------------

def test_is_cf_app(tmp_path):
    assert CF._is_cf_app(tmp_path) is False
    (tmp_path / "cloudflare.config.ts").write_text("export default {}")
    assert CF._is_cf_app(tmp_path) is True


def test_harden_vendors_braces_for_cf_app(tmp_path):
    (tmp_path / "cloudflare.config.ts").write_text(
        'export default { compatibilityDate: "2099-01-01" }')
    (tmp_path / "package.json").write_text(json.dumps({"name": "x"}))
    summary = CF.harden_cf_app(tmp_path, version="1.20240925.0")
    assert summary["vendored_braces"] is True
    assert (tmp_path / "vendor" / "braces" / "node_modules" / "fill-range").is_dir()


def test_harden_no_vendor_for_plain_app(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"name": "x"}))
    summary = CF.harden_cf_app(tmp_path, version="1.20240925.0")
    assert summary["vendored_braces"] is False
    assert not (tmp_path / "vendor").exists()
