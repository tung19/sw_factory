"""area.memory — experience store: remember pitfalls, inject them into prompts.

Leaf module (imports nothing from area). A JSONL of lessons at
workspace/.area/memory.jsonl. Build/heal loops append the failures they had to
overcome; stages recall the relevant ones and prepend them as "known pitfalls"
so the agent avoids repeating them. Seeded with the vinext compat-date gotcha.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Iterable

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


# Where the build agent writes the lesson it learned, in its own working directory.
# Asked for in the retry prompt and harvested by `run_until`, which deletes it — so it
# never reaches the artifact digest. See `parse_lesson` for why it is not free-form.
LESSON_FILE = ".area-lesson.md"
_LESSON_MAX = 400


def parse_lesson(text: str) -> tuple[str, str]:
    """Pull (symptom, fix) out of what the agent wrote. ("", "") if either is missing.

    Deliberately strict, for two reasons that have nothing to do with tidiness:

    1. **This text becomes part of a later prompt.** `as_prompt` renders it under a
       `=== ... ===` header, so a lesson containing such a line could forge a new
       prompt section. Those are stripped, and each half is collapsed to one line.
       In Flow B the build agent has been reading an UNTRUSTED reference repo, so the
       text it writes here is not automatically trustworthy input for the next agent.
    2. **Both halves are required** (see `remember`). A lesson with no fix is the
       defect this whole mechanism replaced.
    """
    sym = fix = ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("==") or line.startswith("---"):
            continue       # never let stored text forge a prompt section boundary
        low = line.lower()
        if low.startswith("symptom:") and not sym:
            sym = line.split(":", 1)[1].strip()
        elif low.startswith("fix:") and not fix:
            fix = line.split(":", 1)[1].strip()
    sym, fix = _deforge(sym)[:_LESSON_MAX], _deforge(fix)[:_LESSON_MAX]
    return (sym, fix) if sym and fix else ("", "")


# Only RUNS of `=` forge a section header. Stripping every `=` (the first attempt)
# silently broke the secret scrubber: `area.screen` matches `KEY=value`, so by the
# time `_harvest_lesson` redacted the text there was no `=` left to match, and
# `DATABASE_URL=postgres://u:pw@h/db` was stored intact as `DATABASE_URLpostgres://...`.
# It also mangled legitimate text like `npm install --omit=dev`. A guard must not
# disable another guard.
_EQ_RUN = re.compile(r"={2,}")


def _deforge(s: str) -> str:
    return _EQ_RUN.sub(" ", s).strip()


def _load() -> list[dict[str, Any]]:
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


def lessons() -> list[dict[str, Any]]:
    _ensure_seed()
    return _load()


def remember(symptom: str, fix: str = "", tags: Iterable[str] = ()) -> None:
    """Store a lesson. BOTH halves are required: a symptom with no resolution is
    not a lesson, and this store is injected into prompts (see `as_prompt`).

    The `fix` guard is the whole point. `run_until` used to call this with only
    `first_fail` and no `fix`, on any build that passed after a retry — so what
    reached the top of every later build prompt, under a header reading "avoid
    these", was four entries that were: a `No such file or directory` on a stale
    path, raw `npm audit` output truncated mid-table, `No test files found,
    exiting with code 1`, and the acceptance oracle's own `FORBIDDEN: files under
    __tests__/_holdout/ were modified` rejection — i.e. the message that proves
    the oracle WORKED, recycled as a pitfall to avoid.

    Harness2 (arXiv:2610.14224) states the rule this restores: keep a lesson only
    when the evidence supports it, otherwise add no entry. Note the gate used by
    `evals.record_experience` cannot be reused here — that one needs a verdict
    over >=5 matched-pair runs, and this writes mid-build where none exists. The
    available evidence at that moment is whether we know what FIXED the failure,
    so that is what is required. See docs/harness2-gap-assessment.md F1.
    """
    _ensure_seed()
    rec: dict[str, Any] = {
        "ts": time.time(),
        "tags": [t for t in tags if t],
        "symptom": symptom.strip()[:500],
        "fix": fix.strip()[:500],
    }
    if not rec["symptom"] or not rec["fix"]:
        return
    for e in _load():  # de-dup identical symptom+tags
        if e.get("symptom") == rec["symptom"] and set(e.get("tags", [])) == set(rec["tags"]):
            return
    try:
        with MEM.open("a") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass


def recall(tags: Iterable[str] = (), text: str = "", limit: int = 5) -> list[dict[str, Any]]:
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


def as_prompt(lessons_: list[dict[str, Any]]) -> str:
    if not lessons_:
        return ""
    lines = ["=== Known pitfalls from past runs (avoid these) ==="]
    for e in lessons_:
        lines.append(f"- {e.get('symptom', '')}")
        if e.get("fix"):
            lines.append(f"  FIX: {e['fix']}")
    return "\n".join(lines) + "\n\n"
