"""The 'command box' = `area iterate`: fold a NL change request INTO the existing
spec (never raw to the agent), re-lock the oracle (TDD), rebuild. Pure logic —
run_pipeline is stubbed, no agents. Covers requirement composition, prior-spec
load, target auto-detect, the pipeline wiring, and the dashboard job command."""

import area.pipeline as P
import area.web.jobs as J


# ---- requirement composition (the governance seam) --------------------------

def test_compose_no_prior_returns_request():
    assert P.compose_amended_requirement("", "add a delete button") == "add a delete button"


def test_compose_folds_request_into_spec():
    out = P.compose_amended_requirement("name: Tip\nsummary: calc tip", "add dark mode")
    assert "CURRENT SPEC" in out and "CHANGE REQUEST" in out
    assert "calc tip" in out and "add dark mode" in out
    # keeps the governance instruction: don't silently drop existing criteria
    assert "do not silently drop" in out.lower() or "except where" in out.lower()


def test_prior_spec_text_reads_both_files(tmp_path):
    sd = tmp_path / "specs" / "app"
    sd.mkdir(parents=True)
    (sd / "spec.yaml").write_text("name: App\nsummary: does x")
    (sd / "acceptance.yaml").write_text("criteria:\n  - AC-1 x works")
    txt = P._prior_spec_text(tmp_path, "app")
    assert "does x" in txt and "AC-1 x works" in txt
    assert "spec.yaml" in txt and "acceptance.yaml" in txt


def test_prior_spec_text_empty_when_missing(tmp_path):
    assert P._prior_spec_text(tmp_path, "nope") == ""


def test_detect_target_cloudflare(tmp_path):
    (tmp_path / "cloudflare.config.ts").write_text("export default {}")
    assert P._detect_iterate_target(tmp_path) == "cloudflare"


def test_detect_target_plain(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts":{"build":"next build"}}')
    assert P._detect_iterate_target(tmp_path) == "plain"


# ---- iterate_pipeline wiring -------------------------------------------------

def test_iterate_passes_amended_requirement_and_autodetects_target(monkeypatch, tmp_path):
    # existing cloudflare app + spec
    (tmp_path / "apps" / "myapp").mkdir(parents=True)
    (tmp_path / "apps" / "myapp" / "cloudflare.config.ts").write_text("x")
    sd = tmp_path / "specs" / "myapp"
    sd.mkdir(parents=True)
    (sd / "spec.yaml").write_text("summary: current behavior here")

    captured = {}

    def fake_run(requirement, **kw):
        captured["requirement"] = requirement
        captured.update(kw)

        class R:
            name = "myapp"
            app_dir = tmp_path / "apps" / "myapp"
            passed = True
            spec_dir = sd
            clarify_needed = False
        return R()

    monkeypatch.setattr(P, "run_pipeline", fake_run)
    P.iterate_pipeline("myapp", "add a logout button", workspace=tmp_path)

    assert "current behavior here" in captured["requirement"]
    assert "add a logout button" in captured["requirement"]
    assert captured["target"] == "cloudflare"   # auto-detected from the app
    assert captured["tdd"] is True              # oracle re-locked by default
    assert captured["name"] == "myapp"


def test_iterate_tdd_can_be_disabled(monkeypatch, tmp_path):
    (tmp_path / "apps" / "a").mkdir(parents=True)
    captured = {}
    monkeypatch.setattr(P, "run_pipeline",
                        lambda req, **kw: captured.update(kw) or type("R", (), {
                            "name": "a", "app_dir": tmp_path, "passed": True,
                            "spec_dir": tmp_path, "clarify_needed": False})())
    P.iterate_pipeline("a", "tweak", tdd=False, workspace=tmp_path)
    assert captured["tdd"] is False


# ---- dashboard job command --------------------------------------------------

def test_cmd_iterate_basic():
    cmd = J.MANAGER._cmd("iterate", {"name": "app", "instruction": "add dark mode"})
    assert cmd[1] == "iterate" and cmd[2] == "app" and cmd[3] == "add dark mode"
    assert "--tdd" not in cmd and "--no-tdd" not in cmd  # TDD on by default, not opted out


def test_cmd_iterate_opt_out_tdd_and_gates():
    cmd = J.MANAGER._cmd("iterate", {
        "name": "app", "instruction": "x", "tdd": False, "e2e": True, "deploy": True,
    })
    assert "--no-tdd" in cmd and "--e2e" in cmd and "--deploy" in cmd and "--yes" in cmd
    assert "--tdd" not in cmd  # never leaks the run-style flag into iterate


def test_cmd_iterate_with_target():
    cmd = J.MANAGER._cmd("iterate", {"name": "a", "instruction": "x", "target": "plain"})
    assert cmd[cmd.index("--target") + 1] == "plain"
