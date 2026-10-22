"""area.build.cf_scaffold — the deterministic vinext fixes. Pure date derivation,
compat-date rewriting, the npm-override merge, and harden_cf_app on a fake app.
The `npm ls workerd` subprocess is bypassed by injecting `version=`; no live build
or network is touched."""
import json

import area.build.cf_scaffold as CF


# ---- date_from_workerd_version --------------------------------------------------

def test_date_from_workerd_version_ok():
    assert CF.date_from_workerd_version("1.20240925.0") == "2024-09-25"
    assert CF.date_from_workerd_version(" 1.20251231.3 ") == "2025-12-31"


def test_date_from_workerd_version_rejects_bad():
    assert CF.date_from_workerd_version("2.0.0") is None          # not a date middle
    assert CF.date_from_workerd_version("1.abcdefgh.0") is None    # non-numeric
    assert CF.date_from_workerd_version("1.20241399.0") is None    # month 13
    assert CF.date_from_workerd_version("1.2024.0") is None        # too short
    assert CF.date_from_workerd_version("nope") is None


# ---- rewrite_compat_date --------------------------------------------------------

def test_rewrite_compat_date_ts_and_toml():
    ts = 'export default { compatibilityDate: "2099-01-01", flags: [] }'
    new, changed = CF.rewrite_compat_date(ts, "2024-09-25")
    assert changed and 'compatibilityDate: "2024-09-25"' in new

    toml = "compatibility_date = '2099-01-01'\n"
    new2, changed2 = CF.rewrite_compat_date(toml, "2024-09-25")
    assert changed2 and "compatibility_date = '2024-09-25'" in new2


def test_rewrite_compat_date_no_match_is_unchanged():
    text = "export default { flags: [] }"
    new, changed = CF.rewrite_compat_date(text, "2024-09-25")
    assert not changed and new == text


# ---- pin_compat_date ------------------------------------------------------------

def test_pin_compat_date_rewrites_config(tmp_path):
    cfg = tmp_path / "cloudflare.config.ts"
    cfg.write_text('export default { compatibilityDate: "2099-12-31" }')
    date = CF.pin_compat_date(tmp_path, version="1.20240925.0")
    assert date == "2024-09-25"
    assert 'compatibilityDate: "2024-09-25"' in cfg.read_text()


def test_pin_compat_date_no_config_returns_none(tmp_path):
    assert CF.pin_compat_date(tmp_path, version="1.20240925.0") is None


def test_pin_compat_date_bad_version_returns_none(tmp_path):
    (tmp_path / "cloudflare.config.ts").write_text('compatibilityDate: "2099-01-01"')
    assert CF.pin_compat_date(tmp_path, version="2.0.0") is None


# ---- apply_cve_overrides --------------------------------------------------------

def test_apply_cve_overrides_adds_both(tmp_path):
    pkg = tmp_path / "package.json"
    pkg.write_text(json.dumps({"name": "x", "dependencies": {}}))
    assert CF.apply_cve_overrides(tmp_path) is True
    ov = json.loads(pkg.read_text())["overrides"]
    assert ov["fflate"] == "^0.7.5"
    assert ov["braces"] == "file:./vendor/braces"


def test_apply_cve_overrides_idempotent_and_preserves(tmp_path):
    pkg = tmp_path / "package.json"
    pkg.write_text(json.dumps({"name": "x",
                               "overrides": {"braces": "file:./vendor/braces",
                                             "fflate": "^0.7.5", "keep": "1.0.0"}}))
    assert CF.apply_cve_overrides(tmp_path) is False   # already present → no change
    assert json.loads(pkg.read_text())["overrides"]["keep"] == "1.0.0"  # preserved


def test_apply_cve_overrides_no_pkg_is_false(tmp_path):
    assert CF.apply_cve_overrides(tmp_path) is False


# ---- harden_cf_app --------------------------------------------------------------

def test_harden_cf_app_runs_both(tmp_path):
    (tmp_path / "cloudflare.config.ts").write_text('compatibilityDate: "2099-01-01"')
    (tmp_path / "package.json").write_text(json.dumps({"name": "x"}))
    summary = CF.harden_cf_app(tmp_path, version="1.20240925.0")
    assert summary["compat_date"] == "2024-09-25"
    assert summary["cve_overrides"] is True


def test_harden_cf_app_non_cf_is_noop(tmp_path):
    summary = CF.harden_cf_app(tmp_path, version="1.20240925.0")
    assert summary["compat_date"] is None and summary["cve_overrides"] is False


# ---- _find_workerd (npm ls --json walk) -----------------------------------------

def test_find_workerd_nested():
    tree = {"dependencies": {
        "vinext": {"version": "0.1.0", "dependencies": {
            "workerd": {"version": "1.20240925.0"}}}}}
    assert CF._find_workerd(tree) == "1.20240925.0"
    assert CF._find_workerd({"dependencies": {}}) is None
