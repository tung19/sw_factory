"""ADR 0004 Stage 0 — the engine-free helpers, and the modules repointed to them, must NOT
drag in the vendored OpenHands SDK.

Checked in a FRESH interpreter each time: this test session has almost certainly already
imported openhands, so `import area.engine_util; 'openhands' in sys.modules` would be a false
positive in-process. A subprocess starts clean.
"""
from __future__ import annotations

import subprocess
import sys


def _pulls_openhands(module: str) -> bool:
    code = (
        f"import {module}\n"
        "import sys\n"
        "print(any(m == 'openhands' or m.startswith('openhands.') for m in sys.modules))\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, f"import {module} failed:\n{r.stderr}"
    return r.stdout.strip() == "True"


def test_engine_util_is_openhands_free() -> None:
    assert not _pulls_openhands("area.engine_util")


def test_scrubbed_env_consumers_are_openhands_free() -> None:
    # These gates only need scrubbed_env; after Stage 0 they import it from the leaf and so
    # must not load the agent SDK (the leak this ADR closes).
    for m in ("area.verify.nfr", "area.verify.perf", "area.build.cf_scaffold"):
        assert not _pulls_openhands(m), f"{m} transitively imports openhands"


def test_area_engine_still_exposes_the_helpers() -> None:
    # The agent-side API is unchanged: `from area.engine import X` still works (it re-exports
    # the leaf). This one is allowed to pull openhands (area.engine loads the adapter).
    code = (
        "from area.engine import Backend, VerifyResult, Verifier, scrubbed_env, "
        "command_verifier, pytest_verifier\n"
        "print('ok')\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stderr
