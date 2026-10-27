"""`SECURITY.md` claims every agent/build/provider subprocess has a wall clock.

It did not. The audit's M1 named two `npm ls` calls; sweeping for the whole class found
**six** uncapped `subprocess.run` sites, including the two longest commands in the
factory — `cf_scaffold._npm_run` (`npm run build:cf`, the CF fallback build) and
`nfr.measure`'s `--nfr-build` full production build. A hung build there wedges the run
with no output and no clock, and the cost gate cannot help: it only measures after the
money is spent.

This test is the reason the claim can now be made and stay made. It sweeps `area/` and
fails on a new uncapped call, so the next one has to be a deliberate entry below rather
than an oversight.
"""
import ast
import re
from pathlib import Path

import pytest

from area.paths import REPO

# Sites that must NOT have a wall clock, with the reason. Anything else uncapped fails.
ALLOWED_UNCAPPED = {
    # The operator's $EDITOR, opened for them to type into. A timeout would kill their
    # session mid-sentence.
    ("area/cli.py", "_edit_via_editor"),
}

# `Popen` sites that deliberately outlive the call, with how they are bounded instead.
ALLOWED_UNBOUNDED_POPEN = {
    # A dashboard job runs for as long as the build takes — that is the point. It is
    # registered in `_procs` and stopped explicitly by `JobManager.cancel()`, which
    # signals the whole process group; a wall clock here would kill real builds.
    ("area/web/jobs.py", "start"),
}


def _calls(path: Path):
    """Every subprocess.run / subprocess.Popen call, with the function enclosing it."""
    tree = ast.parse(path.read_text())
    out = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if (isinstance(f, ast.Attribute) and f.attr in ("run", "Popen")
                    and isinstance(f.value, ast.Name) and f.value.id == "subprocess"):
                out.append((fn.name, f.attr, node))
    return out


def _has_timeout(node: ast.Call) -> bool:
    return any(k.arg == "timeout" for k in node.keywords)


@pytest.mark.parametrize("path", sorted(p for p in (REPO / "area").rglob("*.py")),
                         ids=lambda p: str(p.relative_to(REPO)))
def test_no_uncapped_subprocess_run(path):
    """`subprocess.run` blocks forever without `timeout=`. `Popen` is exempt: it returns
    immediately and its wall clock belongs on the `communicate(timeout=…)` that follows."""
    rel = str(path.relative_to(REPO))
    offenders = [fname for fname, kind, node in _calls(path)
                 if kind == "run" and not _has_timeout(node)
                 and (rel, fname) not in ALLOWED_UNCAPPED]
    assert not offenders, (
        f"{rel}: uncapped subprocess.run in {sorted(set(offenders))} — pass "
        "`timeout=cmd_timeout_or_none()` or add a reasoned entry to ALLOWED_UNCAPPED")


def test_every_popen_is_followed_by_a_bounded_wait():
    """A `Popen` without a bounded `communicate`/`wait` is the same hang by another
    route. Checked textually per function, since the call and the wait are separate
    statements."""
    bad = []
    for path in sorted((REPO / "area").rglob("*.py")):
        rel = str(path.relative_to(REPO))
        src = path.read_text()
        for fname, kind, _ in _calls(path):
            if kind != "Popen" or (rel, fname) in ALLOWED_UNBOUNDED_POPEN:
                continue
            m = re.search(rf"def {re.escape(fname)}\(", src)
            body = src[m.start():] if m else src
            nxt = re.search(r"\ndef ", body[1:])
            body = body[:nxt.start()] if nxt else body
            if "timeout" not in body and "_wait_ready" not in body:
                bad.append(f"{rel}:{fname}")
    assert not bad, (
        f"Popen with neither a bounded wait nor an explicit cancel path: {bad} — "
        "bound the wait, or add a reasoned entry to ALLOWED_UNBOUNDED_POPEN")


def test_the_allow_lists_still_describe_real_code():
    """An allow-list that names a function which has been renamed stops protecting
    anything while still looking like a decision. Both entries must resolve."""
    for rel, fname in sorted(ALLOWED_UNCAPPED | ALLOWED_UNBOUNDED_POPEN):
        src = (REPO / rel).read_text()
        assert re.search(rf"\n\s*def {re.escape(fname)}\(", src), (
            f"{rel}: allow-listed function {fname}() no longer exists")


def test_one_dial_not_several():
    """The timeout default used to be defined in the adapter only, while four other
    modules had none. There must be exactly one definition, so SECURITY.md's claim
    cannot drift from the code again."""
    hits = []
    for path in sorted((REPO / "area").rglob("*.py")):
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if re.match(r"\s*\w*CMD_TIMEOUT_DEFAULT\s*=\s*\d", line):
                hits.append(f"{path.relative_to(REPO)}:{i}")
    assert len(hits) == 1, f"CMD_TIMEOUT_DEFAULT defined in {len(hits)} places: {hits}"


def test_the_dial_is_read_at_call_time_and_can_be_disabled(monkeypatch):
    from area._util import CMD_TIMEOUT_DEFAULT, cmd_timeout, cmd_timeout_or_none

    monkeypatch.delenv("AREA_CMD_TIMEOUT", raising=False)
    assert cmd_timeout() == CMD_TIMEOUT_DEFAULT
    monkeypatch.setenv("AREA_CMD_TIMEOUT", "42")
    assert cmd_timeout() == 42.0 and cmd_timeout_or_none() == 42.0
    monkeypatch.setenv("AREA_CMD_TIMEOUT", "0")          # explicit opt-out
    assert cmd_timeout() == 0.0 and cmd_timeout_or_none() is None
    monkeypatch.setenv("AREA_CMD_TIMEOUT", "not-a-number")
    assert cmd_timeout() == CMD_TIMEOUT_DEFAULT          # garbage -> the default, not 0
