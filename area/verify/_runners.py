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

import re


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
