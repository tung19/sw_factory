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
