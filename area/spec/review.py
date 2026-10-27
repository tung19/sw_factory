"""area.spec.review — INDEPENDENT spec-vs-intent review (anti blind-spot).

The spec stage writes spec.yaml / acceptance.yaml / assumptions.yaml AND self-judges
which ambiguities are "material". That is the same reasoning grading its own work —
exactly what the oracle-loop forbids for CODE (holdout), but left unguarded at the
SPEC layer. For a vague requirement that is the dominant risk: the loop then converges
rigorously onto a confident WRONG guess.

This module adds the missing independence at the spec layer: a SEPARATE, keyless
reviewer that sees ONLY the original requirement + the produced spec, and hunts for
MATERIAL ambiguities the spec stage MISSED or under-rated (the decisions where a
wrong default would change what gets built). Its findings are merged into the
assumptions ledger so the --clarify gate surfaces them to the human BEFORE any build.
This is validation of intent, not verification of code.

Keyless (Claude Code CLI, print mode). Degrades to [] on ANY failure, so an
unavailable reviewer never blocks a build (fail-open — it can only ADD questions).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

import yaml

from area.engine import ask_cli

SENTINEL = "<<<REVIEW>>>"


def _review_prompt(requirement: str, spec_text: str, acc_text: str, assumptions_text: str) -> str:
    """Pure. The independent reviewer's single-shot prompt."""
    return (
        "You are an INDEPENDENT requirements reviewer for a software factory. You did "
        "NOT write the spec below; your ONLY job is to protect against building the "
        "WRONG product from an unclear requirement.\n\n"
        "Given the ORIGINAL requirement and the spec derived from it, find the MATERIAL "
        "ambiguities that the spec's own assumptions ledger MISSED or under-rated — the "
        "decision points where a wrong default would significantly change what the app "
        "IS or who it serves (scope, core behavior, data model, persistence, auth, the "
        "primary user). Do NOT repeat ambiguities already listed as material. Do NOT "
        "invent nitpicks; only decisions that genuinely reshape the product.\n\n"
        f"=== ORIGINAL REQUIREMENT ===\n{requirement.strip()}\n\n"
        f"=== spec.yaml ===\n{spec_text.strip()}\n\n"
        f"=== acceptance.yaml ===\n{acc_text.strip()}\n\n"
        f"=== assumptions.yaml (what the spec stage already flagged) ===\n{assumptions_text.strip()}\n\n"
        "Output ONLY the sentinel on its own line followed by a YAML list (or an empty "
        "list `[]` if the spec is genuinely unambiguous). Nothing after it:\n"
        f"{SENTINEL}\n"
        "- question: <the decision the requirement leaves open>\n"
        "  assumption: <the default the build would otherwise silently pick>\n"
        "  material: true\n"
    )


def _parse_review(raw: str) -> list[dict[str, Any]]:
    """Pure. Parse the reviewer's reply into a list of material-assumption dicts.

    Tolerates code fences and leading prose; reads the YAML list after the sentinel
    (or the whole reply if the sentinel is absent). Keeps only well-formed items that
    name a question and are flagged material. Never raises.
    """
    text = (raw or "").strip()
    if SENTINEL in text:
        text = text.split(SENTINEL, 1)[1].strip()
    # strip a ```yaml ... ``` fence if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if "```" in text:
            text = text.rsplit("```", 1)[0]
    try:
        data = yaml.safe_load(text)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        q = str(item.get("question", "")).strip()
        if not q:
            continue
        if str(item.get("material", "true")).strip().lower() in ("false", "no", "0"):
            continue
        out.append({
            "question": q,
            "assumption": str(item.get("assumption", "")).strip(),
            "material": True,
            "source": "independent-review",
        })
    return out


def review_spec(
    requirement: str,
    spec_dir: str | Path,
    *,
    backend: str = "acp",
    model: Optional[str] = None,
    ask: Optional[Callable[[str], str]] = None,
) -> list[dict[str, Any]]:
    """Independently review requirement->spec and return EXTRA material ambiguities
    the spec stage missed. Fail-open: any error (no requirement, missing files, CLI
    unavailable, bad output) returns [] so a build is never blocked by the reviewer.

    `ask` is an injection seam for tests (defaults to the keyless Claude Code CLI).
    """
    req = (requirement or "").strip()
    if not req:
        return []
    d = Path(spec_dir)
    try:
        spec_text = (d / "spec.yaml").read_text()
        acc_text = (d / "acceptance.yaml").read_text()
    except Exception:
        return []
    assumptions_text = ""
    try:
        assumptions_text = (d / "assumptions.yaml").read_text()
    except Exception:
        pass
    prompt = _review_prompt(req, spec_text, acc_text, assumptions_text)
    try:
        raw = (ask or (lambda p: ask_cli(p, model=model, label="spec-review")))(prompt)
    except Exception as e:  # noqa: BLE001 — reviewer is advisory; never crash a build
        print(f"[area] spec-review skipped (reviewer unavailable): {type(e).__name__}")
        return []
    return _parse_review(raw)
