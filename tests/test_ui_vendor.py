"""area.build.ui_vendor — vendoring the captured reference UI into the clone app."""
from area.build.ui_vendor import VENDOR_DIR, install_ui_evidence, ui_preamble


def _fake_ui(root):
    ui = root / "_ui"
    (ui / "styles").mkdir(parents=True)
    (ui / "assets").mkdir(parents=True)
    (ui / "styles" / "a.css").write_text("body{color:#111}")
    (ui / "assets" / "logo.svg").write_text("<svg/>")
    (ui / "tokens.json").write_text('{"colors":["#111"]}')
    (ui / "manifest.yaml").write_text("captured: true\n")
    return ui


def test_install_ui_evidence_copies_and_is_idempotent(tmp_path):
    _fake_ui(tmp_path)
    app = tmp_path / "app"
    copied = install_ui_evidence(app, tmp_path / "_ui")

    assert set(copied) == {"styles", "assets", "tokens.json", "manifest.yaml"}
    assert (app / VENDOR_DIR / "styles" / "a.css").read_text() == "body{color:#111}"
    assert (app / VENDOR_DIR / "assets" / "logo.svg").exists()
    assert (app / VENDOR_DIR / "tokens.json").exists()

    # second run must not raise and leaves the same files in place
    again = install_ui_evidence(app, tmp_path / "_ui")
    assert set(again) == set(copied)
    assert (app / VENDOR_DIR / "styles" / "a.css").exists()


def test_install_ui_evidence_missing_dir_is_noop(tmp_path):
    assert install_ui_evidence(tmp_path / "app", tmp_path / "nope") == []


def test_ui_preamble():
    assert ui_preamble([]) == ""
    text = ui_preamble(["styles", "tokens.json"])
    assert VENDOR_DIR in text and "PARITY" in text
