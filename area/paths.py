"""area.paths — the ONE place the factory's filesystem layout is defined.

- REPO: the factory checkout (where the `area` CLI, tools/, skills live). Fixed.
- WORKSPACE: where GENERATED products live (apps/<name>, specs/<name>, and the
  .area/ telemetry). Defaults to <repo>/workspace, but set AREA_WORKSPACE to move
  it OUT of the repo so generated apps stay isolated from the factory source you
  are editing/updating (and don't bloat the checkout).

Every module imports WORKSPACE from here (keeping a module-level `WORKSPACE` name
so tests can still monkeypatch `area.<module>.WORKSPACE`). AREA_WORKSPACE is read
once at import, so export it in your shell BEFORE running `area`.
"""
from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def workspace() -> Path:
    e = (os.environ.get("AREA_WORKSPACE") or "").strip()
    return Path(e).expanduser().resolve() if e else REPO / "workspace"


WORKSPACE = workspace()


# The test-file extensions the holdout RUNNER accepts. The authoring gate, the AC
# counter and the provenance oracle-strength field must all agree with it, or a valid
# `.mjs`/`.tsx` holdout is invisible to one of them (findings B8/B10). One definition.
TEST_SUFFIXES = frozenset(
    {".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"}
)


# ---------------------------------------------------------------------------
# What is NOT a built app's authored source: dependency trees, VCS metadata, and
# anything a tool or a gate GENERATES. One set, because there were five.
#
# `area/provenance.py`, `area/verify/visual.py`, `area/re/ui_capture.py`,
# `area/screen.py` and `area/web/jobs.py` each carried their own list and they
# disagreed — so `artifact_digest` hashed directories the rest of AREA treats as
# junk, and an attestation could be invalidated by work that changes no source:
#
#   * `.visual/`  — the visual gate's own score/diff output. Re-running
#                   `area visual <name>` to look at a score broke the attestation.
#   * `coverage/` — written by running the test suite.
#   * `out/`      — Next.js static export output, rewritten by every build.
#   * `.turbo/`   — tool cache.
#
# Same class as M12 (`next-env.d.ts`), found by auditing the seams rather than by
# another incident. Keep this list as the single answer, and add to it here.
GENERATED_DIRS = frozenset({
    # dependencies + VCS
    "node_modules", ".git",
    # framework / deploy build output
    ".next", ".vinext", ".open-next", ".cloudflare", ".wrangler", ".vercel", "out",
    # tool + gate output
    ".turbo", "coverage", ".visual", "test-results", "playwright-report",
    # agent + factory bookkeeping inside a built app
    ".openhands", ".area", ".claude",
})

# Names that are ALSO plausible source directory names, so they are only junk at the
# app ROOT — `src/build/helpers.ts` is real source and was once silently excluded.
GENERATED_AT_ROOT = frozenset({"dist", "build"})
