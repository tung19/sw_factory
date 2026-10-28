"""Five lists said what "not app source" means, and they disagreed.

`area/provenance.py`, `area/verify/visual.py`, `area/re/ui_capture.py`,
`area/screen.py` and `area/web/jobs.py` each carried their own set. Measured divergence:
`artifact_digest` **hashed** `.visual/`, `coverage/`, `out/` and `.turbo/` — all of
which the other modules already treated as generated. So an attestation could be
invalidated by work that changes no source at all:

  * re-running `area visual <name>` to look at a score rewrites `.visual/score.json`;
  * running the test suite writes `coverage/`;
  * a Next.js static export (`output: 'export'`) rewrites `out/` on every build.

Same class as M12 (`next-env.d.ts`), but found by auditing the seams instead of by
another incident — and found on the Flow B path, which has never been run on this code.

The guard that matters here is the last one: it fails if any module ever again decides
something is junk that the attestation still digests.
"""
import pytest

from area.paths import GENERATED_AT_ROOT, GENERATED_DIRS
from area.provenance import _SKIP_ANYWHERE, _SKIP_TOPLEVEL, artifact_digest


def _app(tmp_path):
    app = tmp_path / "apps" / "a"
    (app / "app").mkdir(parents=True)
    (app / "app" / "page.tsx").write_text("export default () => null\n")
    (app / "package.json").write_text('{"name":"a"}')
    return app


@pytest.mark.parametrize("d", [".visual", "coverage", "out", ".turbo"])
def test_the_directories_the_divergence_exposed_are_out_of_the_digest(tmp_path, d):
    app = _app(tmp_path)
    before = artifact_digest(app)
    (app / d).mkdir()
    (app / d / "score.json").write_text('{"combined": 0.91}')
    assert artifact_digest(app) == before, f"{d}/ still changes the artifact digest"


def test_looking_at_a_visual_score_does_not_break_the_attestation(tmp_path):
    """The concrete operator action: build, attest, then re-run the visual gate."""
    from area.provenance import verify_provenance, write_provenance
    from area.verify.visual import VISUAL_DIR

    app = _app(tmp_path)
    write_provenance(app, name="a", target="plain", gates={})
    out = app / VISUAL_DIR
    out.mkdir()
    (out / "score.json").write_text('{"combined": 0.83}')
    (out / "pixel.json").write_text("{}")

    status, why = verify_provenance(app)
    assert status == "ok", f"re-reading a visual score broke the attestation: {why}"


def test_running_the_tests_does_not_break_the_attestation(tmp_path):
    from area.provenance import verify_provenance, write_provenance

    app = _app(tmp_path)
    write_provenance(app, name="a", target="plain", gates={})
    (app / "coverage").mkdir()
    (app / "coverage" / "lcov.info").write_text("TN:\n")
    assert verify_provenance(app)[0] == "ok"


def test_a_source_dir_named_build_is_still_digested(tmp_path):
    """`build`/`dist` are junk only at the ROOT — `src/build/helpers.ts` is real code
    and was once silently excluded."""
    app = _app(tmp_path)
    before = artifact_digest(app)
    (app / "src" / "build").mkdir(parents=True)
    (app / "src" / "build" / "helpers.ts").write_text("export const x = 1\n")
    assert artifact_digest(app) != before

    d = artifact_digest(app)
    (app / "build").mkdir()
    (app / "build" / "bundle.js").write_text("//\n")
    assert artifact_digest(app) == d, "root build/ output entered the digest"


# ---- the guard: no module may disagree with the attestation again -------------

def _module_sets():
    from area.re.ui_capture import _SKIP_DIRS as cap
    from area.verify.visual import _SKIP_DIRS as vis
    from area.web.jobs import _SKIP_DIRS as jobs

    # `.area-ui` is the vendored REFERENCE, not junk: visual and ui_capture exclude it
    # from scanning the clone's own markup so the reference is not compared to itself.
    # That is purpose-specific, not a claim about what app source is.
    return {"visual": vis - {".area-ui"}, "ui_capture": cap - {".area-ui"},
            "jobs": jobs}


@pytest.mark.parametrize("name", sorted(_module_sets()))
def test_no_module_treats_as_junk_what_the_attestation_digests(name):
    digested = _module_sets()[name] - (_SKIP_ANYWHERE | _SKIP_TOPLEVEL)
    assert digested == set(), (
        f"{name} skips {sorted(digested)} as generated, but artifact_digest hashes "
        "them — so work that changes no source can invalidate an attestation"
    )


def test_every_module_derives_from_the_one_set():
    """Not just agreement today: they must be the SAME object's contents, or the next
    edit re-creates the divergence."""
    canonical = set(GENERATED_DIRS) | set(GENERATED_AT_ROOT)
    for name, s in _module_sets().items():
        assert s == canonical, f"{name} has drifted from GENERATED_DIRS: {s ^ canonical}"
    assert _SKIP_ANYWHERE | _SKIP_TOPLEVEL == canonical
