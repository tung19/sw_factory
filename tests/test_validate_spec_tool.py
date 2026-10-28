"""tools/validate-spec.sh — the spec-engine ↔ factory CONTRACT pre-flight.

A spec engine that emits spec.yaml + acceptance.yaml into specs/<name>/ must be able
to prove, before `area run --use-spec`, that its output passes the SAME gate the factory
applies (`area.spec.models.validate_cross` + the pydantic schema). This tool calls that
real code — it does not re-implement the rules — so it can never drift from the factory.

These tests drive the shell script exactly as the factory invokes its siblings
(`bash tools/<x>.sh <name> <workspace>`), on a throwaway workspace.
"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "validate-spec.sh"

_GOOD_SPEC = """\
name: todo
summary: a tiny todo app
stack: nextjs
features:
  - id: add-todo
    title: Add a todo
    description: a user adds an item
routes:
  - {path: "/", purpose: list, kind: page}
"""
_GOOD_ACC = """\
criteria:
  - id: AC-1
    feature: add-todo
    given: an empty list
    when: they add "milk" on /
    then: the list shows "milk"
    verify_by: execution
"""


def _write(ws, name, spec, acc):
    d = ws / "specs" / name
    d.mkdir(parents=True)
    (d / "spec.yaml").write_text(spec)
    (d / "acceptance.yaml").write_text(acc)
    return d


def _run(name, ws, *extra):
    return subprocess.run(
        ["bash", str(SCRIPT), name, str(ws), *extra],
        capture_output=True, text=True)


def test_a_valid_spec_passes(tmp_path):
    _write(tmp_path, "todo", _GOOD_SPEC, _GOOD_ACC)
    r = _run("todo", tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


def test_dangling_feature_reference_fails_and_is_named(tmp_path):
    # AC points at a feature id that spec.yaml does not define → validate_cross rejects.
    bad_acc = _GOOD_ACC.replace("feature: add-todo", "feature: nonexistent")
    _write(tmp_path, "todo", _GOOD_SPEC, bad_acc)
    r = _run("todo", tmp_path)
    assert r.returncode != 0
    assert "nonexistent" in (r.stdout + r.stderr)


def test_navigating_without_declared_routes_fails(tmp_path):
    # criteria navigate to a page but spec.routes is empty → the taskboard-clone trap,
    # which validate_cross makes fatal.
    no_routes = "\n".join(
        ln for ln in _GOOD_SPEC.splitlines()
        if not ln.startswith("routes:") and not ln.strip().startswith("- {path:")
    ) + "\n"
    nav_acc = _GOOD_ACC.replace('when: they add "milk" on /',
                                "when: they request /boards/7")
    _write(tmp_path, "todo", no_routes, nav_acc)
    r = _run("todo", tmp_path)
    assert r.returncode != 0


def test_invalid_yaml_fails_cleanly(tmp_path):
    _write(tmp_path, "todo", "name: [unclosed", _GOOD_ACC)
    r = _run("todo", tmp_path)
    assert r.returncode != 0
    assert "spec.yaml" in (r.stdout + r.stderr)


def test_missing_spec_is_a_usage_error(tmp_path):
    (tmp_path / "specs" / "ghost").mkdir(parents=True)  # dir but no yaml
    r = _run("ghost", tmp_path)
    assert r.returncode != 0


def test_strict_flags_an_unquoted_navigation_even_with_routes(tmp_path):
    # routes ARE declared (so not fatal), but a criterion navigates to /admin which is
    # not among them → advisory under default, a failure under --strict. This is the
    # self-containment contract: the holdout author sees ONLY acceptance.yaml.
    nav_acc = _GOOD_ACC.replace('when: they add "milk" on /',
                                "when: they visit /admin/secret")
    _write(tmp_path, "todo", _GOOD_SPEC, nav_acc)
    assert _run("todo", tmp_path).returncode == 0            # advisory by default
    assert _run("todo", tmp_path, "--strict").returncode != 0  # fatal under --strict


def test_accepts_a_direct_specs_dir_path(tmp_path):
    # a spec engine emits into its own dir, not necessarily $WS/specs/<name>.
    d = _write(tmp_path, "todo", _GOOD_SPEC, _GOOD_ACC)
    r = subprocess.run(["bash", str(SCRIPT), str(d)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
