"""area.spec.clarify — the human's answer to the --clarify gate.

The gate implemented the STOP without the RESUME. It printed "Confirm/override then
re-run", but there was no way to confirm anything:

  * `--expect` is text appended to the EXTRACTION prompt (`extract.expected_block`);
    it never reaches `_clarify_gate`, and giving the extractor more detail makes the
    independent reviewer ask DEEPER questions — measured 8 -> 2 -> 11 material
    assumptions over three runs of the same app;
  * editing `material: false` in `assumptions.yaml` is destroyed, because the
    extractor rewrites that file on every run;
  * no `clarify`/`confirm` verb existed;
  * so the only exit was `--no-clarify`, i.e. the choice was "cannot build" or
    "no gate", with nothing in between — while each attempt cost a fresh spec
    extraction plus an unpriced review.

This does NOT weaken the discipline CLAUDE.md asks for. The rule is "stop and ask
Tung on a material ambiguity"; the stop was unanswerable, and an unanswerable stop
is not a gate, it is a wall. Making it answerable is what lets the human actually be
the top gate.

**Anchored on the spec digest, not on the question text.** Because the gate does not
converge question-by-question, "every question answered" is not a reachable state.
"The human reviewed THIS spec" is, and it is bounded: change the requirement, the
spec changes, the digest changes, and the confirmation expires. `clarified.yaml` is
deliberately NOT in `provenance._MATERIALS`, so recording a confirmation does not
change the digest it is anchored to.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

import yaml

CLARIFIED = "clarified.yaml"


def _digest(spec_dir: Path) -> Optional[str]:
    from area.provenance import spec_digest

    return spec_digest(spec_dir)


def load_record(spec_dir: str | Path) -> dict[str, Any]:
    """The confirmation on file, or {} if absent/unreadable."""
    p = Path(spec_dir) / CLARIFIED
    if not p.exists():
        return {}
    try:
        data = yaml.safe_load(p.read_text()) or {}
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def is_current(spec_dir: str | Path) -> bool:
    """Whether a confirmation covers the spec as it stands right now."""
    rec = load_record(spec_dir)
    if not rec.get("confirmed"):
        return False
    d = _digest(Path(spec_dir))
    return bool(d) and rec.get("spec_digest") == d


def _entry(i: int, q: dict[str, Any], answers: dict[int, str]) -> dict[str, Any]:
    e: dict[str, Any] = {
        "question": str(q.get("question", "")).strip(),
        "assumed": str(q.get("assumption") or q.get("assumed") or "").strip(),
    }
    if i in answers and str(answers[i]).strip():
        e["answer"] = str(answers[i]).strip()
    return e


def confirm(spec_dir: str | Path, questions: list[dict[str, Any]], *,
            answers: Optional[dict[int, str]] = None,
            who: str = "human") -> dict[str, Any]:
    """Record that a human reviewed this exact spec, with what they were shown.

    The questions are stored verbatim so the record says what was actually accepted
    — a confirmation that does not name what it covered is not evidence.
    """
    sd = Path(spec_dir)
    sd.mkdir(parents=True, exist_ok=True)
    answers = answers or {}
    rec = {
        "spec_digest": _digest(sd),
        "when": time.strftime("%Y-%m-%d %H:%M:%S"),
        "by": who,
        "confirmed": True,
        "questions": [_entry(i, q, answers) for i, q in enumerate(questions)],
    }
    (sd / CLARIFIED).write_text(
        "# The human's answer to the --clarify gate. Anchored on the spec digest:\n"
        "# change the requirement and this expires, because it no longer describes\n"
        "# what was reviewed. Written by `area clarify`, never by an agent.\n"
        + yaml.safe_dump(rec, sort_keys=False, allow_unicode=True))
    return rec


def answers_block(spec_dir: str | Path) -> str:
    """The human's explicit answers, as authoritative text for a later extraction.

    Only answers they actually typed — an `--confirm-all` that accepted the agent's
    own assumptions adds nothing here, because repeating a guess back to the
    extractor would dress it up as a decision.
    """
    rec = load_record(spec_dir)
    if not rec.get("confirmed"):
        return ""
    lines = [f"- {q['question']}\n  ANSWER: {q['answer']}"
             for q in rec.get("questions") or []
             if isinstance(q, dict) and q.get("answer") and q.get("question")]
    if not lines:
        return ""
    return ("=== ANSWERED BY THE HUMAN (authoritative; do not re-guess these) ===\n"
            + "\n".join(lines) + "\n")


def open_questions(spec_dir: str | Path) -> list[dict[str, Any]]:
    """Material assumptions still awaiting a human, i.e. the gate's real content."""
    from area.spec.extract import load_assumptions

    material = [a for a in load_assumptions(spec_dir)
                if str(a.get("material")).lower() == "true"]
    return [] if is_current(spec_dir) else material
