#!/usr/bin/env python
"""Phase 1 / Bước 1 demo: requirement -> validated spec artifact (keyless ACP).

Run:  uv run python scripts/04_spec_extract.py
Set AREA_REQUIREMENT to try your own requirement.
"""
import os
from pathlib import Path

from area.spec import extract_spec, validate_cross

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "workspace" / "specs" / "todo"

REQUIREMENT = os.getenv("AREA_REQUIREMENT") or (
    "A minimal todo web app: a user can add a todo with a title, see the list "
    "of todos, mark a todo as done, and delete a todo. No authentication, "
    "single user."
)

spec, acc = extract_spec(REQUIREMENT, OUT)

print("\n=== SPEC ===")
print(f"name     : {spec.name}")
print(f"summary  : {spec.summary}")
print(f"stack    : {spec.stack}")
print(f"entities : {[e.name for e in spec.entities]}")
print(f"features : {[f.id for f in spec.features]}")
print(f"accept.  : {len(acc.criteria)} criteria")
problems = validate_cross(spec, acc)
print("x-check  :", "OK" if not problems else problems)
print(f"\nArtifacts: {OUT / 'spec.yaml'} , {OUT / 'acceptance.yaml'}")
