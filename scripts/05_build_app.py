#!/usr/bin/env python
"""Phase 1 / Bước 2: spec -> working Next.js app (light oracle). Keyless ACP.

Run:  uv run python scripts/05_build_app.py
"""
import sys
from pathlib import Path

from area.build import build_app
from area.spec import load_acceptance, load_spec

ROOT = Path(__file__).resolve().parent.parent
SPEC_DIR = ROOT / "workspace" / "specs" / "todo"
APP_DIR = ROOT / "workspace" / "apps" / "todo"

spec = load_spec(SPEC_DIR / "spec.yaml")
acc = load_acceptance(SPEC_DIR / "acceptance.yaml")

print(f"Building '{spec.name}' ({len(spec.features)} features) -> {APP_DIR}")
passed = build_app(spec, acc, APP_DIR, max_iters=3)
print(f"\n{'✅ BUILD GREEN' if passed else '❌ not green'} — next build + vitest")
sys.exit(0 if passed else 1)
