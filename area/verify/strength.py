"""area.verify.strength — is this criterion's test capable of settling its claim?

AREA's spine is "quality <= strength + INDEPENDENCE of the oracle". Independence is
enforced hard: the holdout is authored by a separate agent from the spec alone, then
checksum-frozen, and the oracle refuses if a locked file was touched or did not
execute. **Strength was never measured at all.**

What that permitted, found by building a real app (`expenses`, 2026-10-28): AC-14
asserted "the app makes no outbound network requests" — a claim about the running
system — and the locked holdout "verified" it by grepping source for HTTP client
names. It reported PASS while `next telemetry status` said `Enabled`, and later FAILED
on a documentation URL inside a comment in a generated file. Maximally independent,
nearly powerless, and nothing anywhere said so. `_authoring_oracle` accepted it
because its coverage check is "the AC id appears in the test text".

So this module measures the one thing that check cannot see: whether the test for a
criterion does the KIND of work its `verify_by` claims. It is pure and deterministic —
no agent, no npm — like the rest of the authoring oracle.

Verdicts are deliberately three-valued, following the practice of reporting an
"unable to verify" result separately from the pass rate rather than folding it into
either. A pass you cannot trust and a failure are different facts.
"""
from __future__ import annotations

import re
from typing import Any

VERIFIED = "verified"              # the method and the test agree
MISMATCH = "method-mismatch"       # claims execution, only inspects the source
UNSTATED = "method-unstated"       # the spec never said how this would be proven
UNCOVERED = "uncovered"            # no test mentions this id at all

# A holdout test reaches the app through its public surface, which CLAUDE.md requires:
# `await import('../../lib/auth')` or `from '../../lib/boards'`. A path that climbs out
# of `__tests__/` is the app; a sibling (`./_source-scan`) is a test helper.
_APP_IMPORT = re.compile(r"""(?:from|import)\s*\(?\s*["'](\.\.\/\.\.\/[^"']+)["']""")
# Reading the artifact instead of running it.
_READS_SOURCE = re.compile(
    r"\b(readFileSync|readdirSync|existsSync|collectSourceFiles|globSync|readdir)\b")


def block_for(text: str, ac_id: str) -> str:
    """The `describe`/`it` block that mentions `ac_id`, by brace matching.

    Falls back to the whole text when the structure cannot be resolved: a detector
    that guesses wrong must guess toward "fine", because a false block on an honest
    suite costs more than a missed weak one. The point is to stop reporting PASS for
    unchecked properties, not to win an argument with a parser.
    """
    i = text.find(ac_id)
    if i < 0:
        return ""
    start = max(text.rfind("describe(", 0, i), text.rfind("it(", 0, i))
    if start < 0:
        return text
    open_brace = text.find("{", start)
    if open_brace < 0:
        return text
    depth = 0
    for j in range(open_brace, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[start:j + 1]
    return text


def exercises_system(block: str) -> bool:
    """Does this block drive the app, rather than read it?"""
    return bool(_APP_IMPORT.search(block))


def inspects_source(block: str) -> bool:
    return bool(_READS_SOURCE.search(block))


def classify(criteria: list[dict[str, Any]], holdout_text: str) -> dict[str, str]:
    """{ac_id: verdict} for every criterion, against the authored suite's text."""
    out: dict[str, str] = {}
    for c in criteria:
        ac = str(c.get("id") or "").strip()
        if not ac:
            continue
        block = block_for(holdout_text, ac)
        if not block:
            out[ac] = UNCOVERED
            continue
        method = str(c.get("verify_by") or "").strip().lower()
        if not method:
            out[ac] = UNSTATED
        elif method == "execution" and inspects_source(block) \
                and not exercises_system(block):
            # The decisive case: a runtime claim proven by reading the source.
            out[ac] = MISMATCH
        else:
            out[ac] = VERIFIED
    return out


def weak(verdicts: dict[str, str]) -> list[str]:
    """The ids whose PASS would not mean what it appears to mean."""
    return sorted(k for k, v in verdicts.items() if v == MISMATCH)


def unstated(verdicts: dict[str, str]) -> list[str]:
    return sorted(k for k, v in verdicts.items() if v == UNSTATED)


def report(verdicts: dict[str, str]) -> str:
    """One line, in the shape the cost gate already uses for partial measurement."""
    n = len(verdicts)
    bad, miss = weak(verdicts), unstated(verdicts)
    ok = n - len(bad) - len(miss) - sum(1 for v in verdicts.values() if v == UNCOVERED)
    bits = [f"{ok} of {n} criteria verified by a method that can settle them"]
    if bad:
        bits.append(f"{len(bad)} UNABLE TO VERIFY ({', '.join(bad)}: declared "
                    "`execution` but the test only reads the source)")
    if miss:
        bits.append(f"{len(miss)} with no stated method ({', '.join(miss)})")
    return "; ".join(bits)
