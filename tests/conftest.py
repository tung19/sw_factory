"""Dogfood test suite for AREA itself (the orchestrator).

These tests cover AREA's own pure logic — the anti-self-certification lock, the
TDD build/challenge ordering, name sanitization, the experience store — WITHOUT
running any live agent (no ACP/OpenHands/npm/network). The agent-driven stages
are stubbed; what we assert here is the orchestration policy AREA is responsible
for, which is exactly where bugs would silently weaken the "oracle".
"""
import os

os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")
