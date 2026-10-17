#!/usr/bin/env python
"""Phase 1 demo: keyless self-correct loop via Claude Code (ACP).

Seeds a FAILING pytest (no implementation provided) and loops the agent until
the test passes. The "oracle" is pytest — no judge LLM, no API key — so this
proves area.engine.run_until works on the no-key ACP backend.

Run:  uv run python scripts/03_selfcorrect_loop.py
"""
import sys
from pathlib import Path

from area.engine import build_agent, pytest_verifier, run_until

ROOT = Path(__file__).resolve().parent.parent
WS = ROOT / "workspace" / "demo_loop"
WS.mkdir(parents=True, exist_ok=True)

# Seed the acceptance test only. The implementation (mathx.py) is the agent's job.
(WS / "test_mathx.py").write_text(
    "from mathx import fizzbuzz\n\n"
    "def test_fizzbuzz():\n"
    "    assert fizzbuzz(3) == 'Fizz'\n"
    "    assert fizzbuzz(5) == 'Buzz'\n"
    "    assert fizzbuzz(15) == 'FizzBuzz'\n"
    "    assert fizzbuzz(2) == '2'\n"
)
# Make sure no stale implementation is lying around from a previous run.
(WS / "mathx.py").unlink(missing_ok=True)

agent = build_agent("acp")  # Claude Code via ACP — your login, no key
try:
    passed, _ = run_until(
        agent,
        workspace=WS,
        task=(
            "Create mathx.py in the working directory with a function "
            "fizzbuzz(n) so that the existing test_mathx.py passes, then run "
            "`python -m pytest -q` to confirm."
        ),
        verify=pytest_verifier("test_mathx.py", cwd=WS),
        max_iters=4,
    )
finally:
    agent.close()

print(f"\n{'✅ PASSED' if passed else '❌ did not pass'} — keyless self-correct loop (ACP + pytest oracle)")
sys.exit(0 if passed else 1)
