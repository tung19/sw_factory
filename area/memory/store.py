"""area.memory — experience store: remember pitfalls, inject them into prompts.

Leaf module (imports nothing from area). A JSONL of lessons at
workspace/.area/memory.jsonl. Build/heal loops append the failures they had to
overcome; stages recall the relevant ones and prepend them as "known pitfalls"
so the agent avoids repeating them. Seeded with the vinext compat-date gotcha.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterable

from area.paths import WORKSPACE  # noqa: E402 (AREA_WORKSPACE-aware single source)

MEM = WORKSPACE / ".area" / "memory.jsonl"

_SEED = [
    {
        "tags": ["build", "cloudflare", "vinext"],
        "symptom": "vinext init writes compatibility_date=today, but the installed "
        "workerd can lag a few days, so `build:cf` (vite build) fails.",
        "fix": "After init, set compatibility_date in cloudflare.config.ts to the "
        "installed workerd release date or earlier (`npm ls workerd`); keep "
        "compatibilityFlags ['nodejs_compat']. Keep Vitest isolated (own "
        "vitest.config.ts, plain node env, no vinext/cloudflare plugins).",
    },
]


def _load() -> list[dict]:
    out = []
    if MEM.exists():
        for line in MEM.read_text(errors="ignore").splitlines():
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def _ensure_seed() -> None:
    if not MEM.exists():
        MEM.parent.mkdir(parents=True, exist_ok=True)
        with MEM.open("w") as f:
            for s in _SEED:
                f.write(json.dumps({**s, "ts": time.time()}) + "\n")


def lessons() -> list[dict]:
    _ensure_seed()
    return _load()


def remember(symptom: str, fix: str = "", tags: Iterable[str] = ()) -> None:
    _ensure_seed()
    rec = {
        "ts": time.time(),
        "tags": [t for t in tags if t],
        "symptom": symptom.strip()[:500],
        "fix": fix.strip()[:500],
    }
    if not rec["symptom"]:
        return
    for e in _load():  # de-dup identical symptom+tags
        if e.get("symptom") == rec["symptom"] and set(e.get("tags", [])) == set(rec["tags"]):
            return
    try:
        with MEM.open("a") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass


def recall(tags: Iterable[str] = (), text: str = "", limit: int = 5) -> list[dict]:
    _ensure_seed()
    tagset = {t.lower() for t in tags}
    words = {w for w in text.lower().split() if len(w) > 3}
    scored = []
    for e in _load():
        et = {t.lower() for t in e.get("tags", [])}
        score = len(tagset & et) * 2
        blob = (e.get("symptom", "") + " " + e.get("fix", "")).lower()
        score += sum(1 for w in words if w in blob)
        if score > 0:
            scored.append((score, e.get("ts", 0), e))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    return [e for _, _, e in scored[:limit]]


def as_prompt(lessons_: list[dict]) -> str:
    if not lessons_:
        return ""
    lines = ["=== Known pitfalls from past runs (avoid these) ==="]
    for e in lessons_:
        lines.append(f"- {e.get('symptom', '')}")
        if e.get("fix"):
            lines.append(f"  FIX: {e['fix']}")
    return "\n".join(lines) + "\n\n"
