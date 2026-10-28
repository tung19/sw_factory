"""A local-path reference was the one clone kind whose UI half silently did nothing.

`capture_ui_evidence` captures from `_sample/`, or from a live http(s) source. The RE
prompt told the agent *"local path -> read the files there"*, so nothing ever created
`_sample/` for a path — and capture returned `no _sample/ tree and source is not an
http(s) URL`. Measured per kind before the fix:

    kind=path  captured=False   no _sample/ tree …
    kind=url   captured=True

With no UI evidence, `_with_ui_parity` has nothing to bolt onto the build oracle and
the visual gate is never auto-selected. So `area clone ./some-app --tdd` — the most
natural invocation there is — produced a GREEN build with the entire UI-parity half of
Flow B inert. That is #35's whole contribution ("the UI is now a TERM IN THE BUILD
ORACLE") disabled by the choice of reference kind, reporting success.

The intent was always otherwise: `ui_capture.capture_ui_evidence`'s own docstring says
"_sample/ tree (repo/**local-path** reference cloned by RE)". This makes the path kind
match what the code already claimed, and in doing so enforces
`.claude/skills/clone-from-source`'s rule that the reference is ISOLATED and READ,
never read in place.
"""
import pytest

from area.paths import GENERATED_AT_ROOT, GENERATED_DIRS
from area.re.extract import isolate_local_path
from area.re.ui_capture import capture_ui_evidence


def _reference(tmp_path):
    """A reference app shaped like the real ones: real source, huge generated trees."""
    ref = tmp_path / "ref"
    (ref / "app").mkdir(parents=True)
    (ref / "app" / "page.tsx").write_text(
        "export default function P() {\n"
        "  return <main className='board'><h1>Boards</h1></main>\n}\n")
    (ref / "app" / "globals.css").write_text(
        ":root { --brand: #2d6cdf; --radius: 8px }\nbody { background: #fff }\n")
    (ref / "package.json").write_text('{"name":"ref","dependencies":{"next":"15"}}')
    for junk in ("node_modules", ".next", ".turbo", "coverage"):
        (ref / junk).mkdir()
        (ref / junk / "big.bin").write_bytes(b"x" * 50_000)
    (ref / "dist").mkdir()
    (ref / "dist" / "out.js").write_text("//\n")
    (ref / "src" / "build").mkdir(parents=True)
    (ref / "src" / "build" / "helpers.ts").write_text("export const x = 1\n")
    return ref


def test_a_local_path_lands_in_sample(tmp_path):
    sd = tmp_path / "specs" / "c"
    sd.mkdir(parents=True)
    n, size = isolate_local_path(str(_reference(tmp_path)), sd)
    assert n > 0 and (sd / "_sample" / "app" / "page.tsx").is_file()
    assert (sd / "_sample" / "package.json").is_file()


@pytest.mark.parametrize("junk", sorted(GENERATED_DIRS & {
    "node_modules", ".next", ".turbo", "coverage"}))
def test_generated_trees_are_not_copied(tmp_path, junk):
    """What makes it affordable: the real references on this machine are 1.2-1.4 GB,
    almost all of it node_modules and .next. The measured result was 53 files / 0.3 MB
    in 0.5s from a 1.4 GB app."""
    sd = tmp_path / "specs" / "c"
    sd.mkdir(parents=True)
    isolate_local_path(str(_reference(tmp_path)), sd)
    assert not (sd / "_sample" / junk).exists()


def test_a_source_dir_named_build_still_comes_along(tmp_path):
    """`dist`/`build` are output only at the ROOT — `src/build/helpers.ts` is source."""
    sd = tmp_path / "specs" / "c"
    sd.mkdir(parents=True)
    isolate_local_path(str(_reference(tmp_path)), sd)
    assert (sd / "_sample" / "src" / "build" / "helpers.ts").is_file()
    assert not (sd / "_sample" / "dist").exists()
    assert GENERATED_AT_ROOT == {"dist", "build"}


def test_isolating_twice_does_not_replace_the_evidence(tmp_path):
    """A re-run must not silently swap the evidence an earlier spec was derived from."""
    sd = tmp_path / "specs" / "c"
    sd.mkdir(parents=True)
    ref = _reference(tmp_path)
    isolate_local_path(str(ref), sd)
    (sd / "_sample" / "app" / "page.tsx").write_text("// the evidence as captured\n")

    n, _ = isolate_local_path(str(ref), sd)
    assert n == 0
    assert "as captured" in (sd / "_sample" / "app" / "page.tsx").read_text()


def test_a_missing_or_file_source_is_a_no_op(tmp_path):
    sd = tmp_path / "specs" / "c"
    sd.mkdir(parents=True)
    assert isolate_local_path(str(tmp_path / "nope"), sd) == (0, 0)
    f = tmp_path / "a-file.txt"
    f.write_text("x")
    assert isolate_local_path(str(f), sd) == (0, 0)


# ---- the point: the UI half of Flow B now runs for a local reference ----------

def test_ui_evidence_is_captured_from_a_local_reference(tmp_path):
    """Before: `captured=False`, "no _sample/ tree and source is not an http(s) URL" —
    so the build oracle had no UI term and the visual gate never auto-selected."""
    sd = tmp_path / "specs" / "c"
    sd.mkdir(parents=True)
    ref = _reference(tmp_path)
    isolate_local_path(str(ref), sd)

    ev = capture_ui_evidence(str(ref), "path", sd)
    assert ev.captured is True, ev.notes
    assert ev.rendered, "no markup captured"
    assert ev.tokens, "no design tokens extracted"


def test_without_isolation_there_is_no_ui_evidence_at_all(tmp_path):
    """The before-state, pinned: this is what a local-path clone used to get."""
    sd = tmp_path / "specs" / "c"
    sd.mkdir(parents=True)
    ev = capture_ui_evidence(str(_reference(tmp_path)), "path", sd)
    assert ev.captured is False
    assert "_sample" in ev.notes


def test_spec_from_source_isolates_before_the_agent_runs(tmp_path, monkeypatch):
    """Wiring, not just capability. The first version of these tests called
    `isolate_local_path` directly and stayed green with the call site removed — proving
    the helper and not the behaviour. Driven through the real `spec_from_source` with
    only the agent stubbed, and the stub asserts `_sample/` already exists when it is
    invoked, because the RE prompt tells the agent to read it there."""
    import area.re.extract as E

    sd = tmp_path / "specs" / "c"
    ref = _reference(tmp_path)
    seen = {}

    def fake_run_until(agent, out, task, verifier, **kw):
        seen["sample_existed"] = (out / "_sample" / "app" / "page.tsx").is_file()
        seen["task"] = task
        (out / "spec.yaml").write_text("name: c\nsummary: a clone\n")
        (out / "acceptance.yaml").write_text(
            "criteria:\n- id: AC-1\n  feature: f\n  given: g\n  when: w\n  then: t\n")
        return True, None

    monkeypatch.setattr(E, "run_until", fake_run_until)
    monkeypatch.setattr(E, "build_agent", lambda *a, **k: _NoopAgent())

    E.spec_from_source(str(ref), sd, kind="path")

    assert seen.get("sample_existed") is True, \
        "spec_from_source did not isolate the reference before running the agent"
    assert "_sample" in seen["task"], "the prompt does not point the agent at _sample"
    assert "never run it" in seen["task"], "the prompt dropped the do-not-run rule"


class _NoopAgent:
    def close(self):
        pass
