# AREA — common tasks. `make setup` once, then `make demo` to see it work.
.PHONY: help setup doctor demo test lint typecheck evals check

VENV := .venv/bin

help:
	@echo "AREA — common tasks:"
	@echo "  make setup   install (venv + deps + vendored engine) and check the environment"
	@echo "  make demo    run the committed example app, KEYLESS (no Claude, no cost)"
	@echo "  make doctor  re-check the local setup"
	@echo "  make test    run the dogfood test suite"
	@echo "  make lint    ruff (pyflakes bugs + syntax)"
	@echo "  make evals   grade a change to the FACTORY itself (prompts/skills/knobs)"
	@echo "  make check   lint + typecheck + tests + evals (what CI runs)"

setup:
	bash scripts/install.sh
	@echo ""
	@echo "→ next:  make demo        (see a real built app run, no Claude key)"
	@echo "         area doctor      (re-check your setup)"
	@echo '         area run "<requirement>" --name myapp --target plain --tdd'

doctor:
	@$(VENV)/area doctor 2>/dev/null || area doctor

demo:
	@$(VENV)/area demo taskboard 2>/dev/null || area demo taskboard

test:
	@$(VENV)/python -m pytest 2>/dev/null || python -m pytest

lint:
	@$(VENV)/ruff check area tests 2>/dev/null || ruff check area tests

typecheck:
	@$(VENV)/mypy 2>/dev/null || mypy

# Grades the FACTORY, not an app: `_GATE_ORDER` decides whether an app may ship,
# this decides whether a change to AREA's own prompts/skills/knobs may be promoted.
# It needs measured runs, which live in YOUR local obs log — so in CI it honestly
# reports "no data" and passes. Run it locally before promoting a prompt change.
evals:
	@$(VENV)/area evals --check 2>/dev/null || area evals --check

check: lint typecheck test evals
