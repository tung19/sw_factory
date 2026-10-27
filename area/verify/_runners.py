"""area.verify._runners — assert a test runner actually EXECUTED tests.

The oracle's core guarantee is "build to green". But a green exit code is not
enough: the app's vitest/playwright config is authored by the builder and is NOT
locked, so `passWithNoTests` or an `include` that matches nothing yields exit 0
with ZERO tests collected — the locked acceptance suite never runs, yet the
oracle would report green. These helpers parse the runner summary and require
positive evidence that tests ran (and, for the holdout, enough of them to cover
the acceptance criteria), so "green" means "the suite actually passed".
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, Optional


def vitest_passed(output: str) -> int | None:
    """Passed-test count from a vitest summary (`Tests  12 passed (12)`, or
    `Tests  2 failed | 10 passed (12)`), or None if no summary is present."""
    ms = re.findall(r"Tests\s+[^\n]*?(\d+)\s+passed", output)
    return int(ms[-1]) if ms else None


def playwright_passed(output: str) -> int | None:
    """Passed-spec count from a Playwright summary (`15 passed (9s)`), or None."""
    ms = re.findall(r"(\d+)\s+passed", output)
    return int(ms[-1]) if ms else None


def _no_tests(output: str) -> bool:
    low = output.lower()
    return ("no test files found" in low or "no tests found" in low
            or "passwithnotests" in low)


def assert_vitest_ran(output: str, min_expected: int = 1) -> tuple[bool, str]:
    """(ok, why): require ≥ max(1, min_expected) vitest tests to have passed."""
    if _no_tests(output):
        return False, "no test files were collected (0 tests ran)"
    passed = vitest_passed(output)
    need = max(1, min_expected)
    if passed is None:
        return False, "could not confirm any test ran (no vitest summary in output)"
    if passed < need:
        return False, f"only {passed} test(s) ran, expected ≥ {need} (one per AC)"
    return True, f"{passed} test(s) passed"


def assert_playwright_ran(output: str) -> tuple[bool, str]:
    """(ok, why): require ≥1 Playwright spec to have actually run."""
    if _no_tests(output):
        return False, "no E2E specs were collected (0 ran)"
    passed = playwright_passed(output)
    if not passed:
        return False, "could not confirm any E2E spec ran"
    return True, f"{passed} spec(s) passed"


# --- did the LOCKED files themselves run? ------------------------------------

def executed_test_files(report: Path) -> Optional[set[str]]:
    """Absolute paths of the test files a vitest JSON report says actually ran, or
    None if the report is missing or unreadable (treated as "cannot confirm", which
    the caller must fail on rather than pass)."""
    try:
        data = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    results = data.get("testResults")
    if not isinstance(results, list):
        return None
    out: set[str] = set()
    for r in results:
        name = r.get("name") if isinstance(r, dict) else None
        if isinstance(name, str) and name:
            out.add(name)
    return out


def assert_locked_files_ran(report: Path, app: Path,
                            locked: Iterable[str]) -> tuple[bool, str]:
    """(ok, why): every locked test file must appear in the runner's own report of
    what it executed.

    `locked` are the holdout lock's keys, which are relative to the HOLDOUT DIRECTORY,
    not to the app root — pass that directory as `app`. (Passing the app root makes
    every file look un-run, which still blocks the attack but also blocks every honest
    build; a real end-to-end run is what caught it.) Comparison is
    by resolved absolute path, so a decoy whose name merely contains the locked
    directory cannot stand in for a locked file. A missing report fails: the whole
    point is to stop trusting a green exit code.
    """
    # Non-test files are legitimately in the lock (e.g. the holdout's CONTRACT.md), so
    # only runnable test sources are required to have executed. Covers every extension
    # vitest will collect, `.mts`/`.cts` included.
    wanted = {p for p in locked
              if p.endswith((".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"))}
    if not wanted:
        return True, "no runnable locked test files to confirm"
    ran = executed_test_files(report)
    if ran is None:
        return False, ("the runner produced no machine-readable report, so WHICH tests "
                       "ran cannot be confirmed")
    ran_resolved = {str(Path(p).resolve()) for p in ran}
    missing = sorted(p for p in wanted
                     if str((app / p).resolve()) not in ran_resolved)
    if missing:
        return False, ("the runner never executed " + ", ".join(missing[:10])
                       + f" ({len(missing)} of {len(wanted)} locked file(s) did not run)")
    return True, f"all {len(wanted)} locked file(s) executed"
