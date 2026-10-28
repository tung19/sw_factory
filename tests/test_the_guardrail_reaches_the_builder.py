"""The locked-holdout guard must protect the agent that WRITES the app, not only
an interactive session in the AREA repo.

`tools/hooks/guard_holdout.py` turns "please don't edit the locked oracle" into
"cannot" — but it was wired from the repo's own `.claude/settings.json`, and nothing
installed anything equivalent into a built app. A built app's `.claude/` held only
`skills/` (measured on ~/area-generated/apps/taskboard). So for the autonomous
builder, holdout protection was detection after the fact — which is exactly how
`author_until` once re-authored an already-locked holdout and rewrote its lock to
match, after which the tamper detector still reported the oracle intact (#33).

`tests/test_guard_holdout.py` covers the hook's LOGIC. This covers its DELIVERY, and
drives the copy that was actually installed, through the real entrypoint.
docs/harness2-gap-assessment.md F3.
"""
import json
import subprocess
import sys
from pathlib import Path

from area.skills import install_guardrail


def _settings(app: Path) -> dict:
    return json.loads((app / ".claude" / "settings.json").read_text())


def _run_installed(app: Path, file_path: str, cwd: str) -> int:
    """Run the hook copy that install_guardrail placed in the app."""
    hook = app / ".claude" / "hooks" / "guard_holdout.py"
    p = subprocess.run(
        [sys.executable, "-I", str(hook)],
        input=json.dumps({"cwd": cwd, "tool_input": {"file_path": file_path}}),
        capture_output=True, text=True,
    )
    return p.returncode


def _app_with_locked_holdout(tmp_path: Path, name: str = "app1") -> tuple[Path, Path]:
    """The real layout: <ws>/apps/<name> plus the lock at <ws>/specs/<name>."""
    app = tmp_path / "apps" / name
    hold = app / "__tests__" / "_holdout"
    hold.mkdir(parents=True)
    (hold / "ac.test.ts").write_text("test('AC-1', () => {});\n")
    spec = tmp_path / "specs" / name
    spec.mkdir(parents=True)
    (spec / "holdout.lock").write_text("deadbeef  ./ac.test.ts\n")
    return app, hold / "ac.test.ts"


def test_install_puts_both_the_hook_and_the_settings_in_place(tmp_path):
    app = tmp_path / "apps" / "a"
    app.mkdir(parents=True)
    assert install_guardrail(app) is True
    assert (app / ".claude" / "hooks" / "guard_holdout.py").is_file()
    pre = _settings(app)["hooks"]["PreToolUse"]
    assert any("guard_holdout.py" in h["command"]
               for m in pre for h in m["hooks"])
    # it must fire on every write-shaped tool, not just Edit
    matchers = [m["matcher"] for m in pre]
    assert any(all(t in m for t in ("Edit", "Write", "MultiEdit", "NotebookEdit"))
               for m in matchers)


def test_installing_twice_does_not_duplicate_the_hook(tmp_path):
    app = tmp_path / "apps" / "a"
    app.mkdir(parents=True)
    install_guardrail(app)
    install_guardrail(app)
    pre = _settings(app)["hooks"]["PreToolUse"]
    assert sum(1 for m in pre for h in m["hooks"]
               if "guard_holdout.py" in h["command"]) == 1


def test_an_existing_settings_file_is_merged_not_replaced(tmp_path):
    app = tmp_path / "apps" / "a"
    (app / ".claude").mkdir(parents=True)
    (app / ".claude" / "settings.json").write_text(json.dumps(
        {"model": "whatever", "hooks": {"PostToolUse": [{"matcher": "Bash",
                                                         "hooks": []}]}}))
    assert install_guardrail(app) is True
    conf = _settings(app)
    assert conf["model"] == "whatever", "an unrelated setting was dropped"
    assert "PostToolUse" in conf["hooks"], "an unrelated hook was dropped"
    assert conf["hooks"]["PreToolUse"], "our hook was not added"


def test_an_unparseable_settings_file_is_never_clobbered(tmp_path):
    app = tmp_path / "apps" / "a"
    (app / ".claude").mkdir(parents=True)
    f = app / ".claude" / "settings.json"
    f.write_text("{ this is not json")
    assert install_guardrail(app) is False
    assert f.read_text() == "{ this is not json"


def test_a_missing_hook_source_reports_failure_rather_than_half_installing(tmp_path):
    app = tmp_path / "apps" / "a"
    app.mkdir(parents=True)
    assert install_guardrail(app, src=tmp_path / "nope.py") is False
    assert not (app / ".claude" / "settings.json").exists()


# ---- the point of all of it: the INSTALLED copy actually blocks ----------------

def test_the_installed_hook_blocks_an_edit_to_the_locked_oracle(tmp_path):
    app, test_file = _app_with_locked_holdout(tmp_path)
    assert install_guardrail(app) is True
    assert _run_installed(app, str(test_file), str(app)) == 2, \
        "the installed guard allowed an edit to a LOCKED holdout"


def test_the_installed_hook_allows_the_authoring_phase_and_the_challenge(tmp_path):
    """Before the lock exists the holdout is being authored, and _CHALLENGE.md is
    the sanctioned escape hatch — blocking either would break the method."""
    app, test_file = _app_with_locked_holdout(tmp_path, "app2")
    install_guardrail(app)
    (tmp_path / "specs" / "app2" / "holdout.lock").unlink()
    assert _run_installed(app, str(test_file), str(app)) == 0

    (tmp_path / "specs" / "app2" / "holdout.lock").write_text("x  ./ac.test.ts\n")
    challenge = test_file.parent / "_CHALLENGE.md"
    assert _run_installed(app, str(challenge), str(app)) == 0


def test_the_installed_hook_leaves_app_code_alone(tmp_path):
    app, _ = _app_with_locked_holdout(tmp_path, "app3")
    install_guardrail(app)
    src = app / "lib" / "auth.ts"
    src.parent.mkdir(parents=True)
    src.write_text("export const x = 1\n")
    assert _run_installed(app, str(src), str(app)) == 0, \
        "the guard blocked ordinary app code"


def test_the_installed_copy_is_byte_identical_to_the_repo_hook(tmp_path):
    """A stale copy in an app would be a guard that no longer matches the one the
    repo tests — the same drift tests/test_skills_in_sync.py exists to prevent."""
    from area.skills import HOOK_SRC

    app = tmp_path / "apps" / "a"
    app.mkdir(parents=True)
    install_guardrail(app)
    assert (app / ".claude" / "hooks" / "guard_holdout.py").read_bytes() == \
        HOOK_SRC.read_bytes()


def test_the_builder_installs_it(tmp_path, monkeypatch):
    """Wiring, not just capability: `build_app` must call it. Driven through the real
    `build_app` — everything before the agent stage is pure (mkdir, yaml, prompt,
    install), so only the agent itself is stubbed."""
    import area.build.nextjs as N
    from area.spec import Acceptance, Spec

    app = tmp_path / "apps" / "app4"
    seen = {}

    def fake_run_until(agent, ws, task, verifier, **kw):
        seen["task"] = task
        return True, None

    monkeypatch.setattr(N, "run_until", fake_run_until)
    monkeypatch.setattr(N, "build_agent", lambda *a, **k: _NoopAgent())

    ok = N.build_app(Spec(name="app4", summary="a thing"), Acceptance(),
                     app, target="plain")

    assert ok is True and "task" in seen, "the build stage never ran; this proves nothing"
    assert (app / ".claude" / "hooks" / "guard_holdout.py").is_file(), \
        "build_app did not install the guardrail"
    assert (app / ".claude" / "skills").is_dir(), "the skills pack regressed"


class _NoopAgent:
    def close(self):
        pass
