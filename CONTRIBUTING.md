# Contributing to AREA

For someone extending the factory itself (not using it to build an app). Read
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) first for the map, and
[CLAUDE.md](CLAUDE.md) for the oracle-loop rules the build agent follows.

## Setup

```bash
git clone <this repo> && cd SW_Factory
bash scripts/install.sh      # uv venv (Python 3.12) + install (incl. the vendored engine) + checks
area doctor                  # Python/Node/git/gh/Claude/deploy creds
```

**uv gotcha:** the venv is created by `uv`, so there is **no `.venv/bin/pip`**. Use
`uv pip …` (with `VIRTUAL_ENV=$PWD/.venv` exported) or `.venv/bin/python -m pip`.
The engine (`openhands-sdk` + `openhands-tools`) installs **editable from
`vendor/software-agent-sdk/`**, not PyPI — it is vendored in-tree (git subtree). Pull
upstream fixes with `git subtree pull --prefix=vendor/software-agent-sdk <repo> <tag> --squash`.

## Tests

```bash
source .venv/bin/activate
make check     # ruff (lint) + mypy (phased subset) + pytest — what CI runs
# or individually:  make lint  ·  make typecheck  ·  make test  (~347 tests, ~2-3s)
```

Lint is `ruff` (pyflakes + syntax). Type-checking is `mypy` on a **phased subset**
of already-clean modules (see `[tool.mypy]` in `pyproject.toml`); growing that list
as modules get typed is a welcome contribution.

The suite is **logic-only and agent-free** — it never spawns a build agent or hits an
LLM (those are validated by dogfood runs). So tests must stub the agent/pipeline and
exercise pure functions, gate dispatch, CLI wiring, and the deterministic shell tools.
CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs `compileall` + pytest on
push/PR to `main` (it strips macOS-only `pyobjc` lines from the lockfile on Linux).

Every change to factory code needs a test. The gates are AREA's product, so a gate
change without a test will silently drift — that is exactly how a security check was
once lost (see the deep-audit history in PLAN.md).

## The rules you must not break

1. **Never weaken oracle independence.** The holdout under `__tests__/_holdout/` is
   authored by an *independent* agent from the spec only and checksum-locked. The build
   agent may not edit it — the `guard_holdout.py` hook enforces this. If a locked test
   is genuinely wrong, the path is `_CHALLENGE.md` → independent re-adjudication → re-lock,
   never a silent edit.
2. **Deterministic gates block; LLM-judgement gates are advisory until `--strict`.** Don't
   promote an LLM/heuristic check to a hard block without measuring its false-positive rate
   first (the research posture in PLAN §SecOps).
3. **A gate that cannot measure must not block.** `nfr`/`perf` *skip* (pass) when there's
   nothing to measure — a measurement failure is not a build failure.
4. **Keep `area/obs.py` a leaf** (it imports nothing from `area`) to avoid cycles. The
   engine seam stays `area/engine/adapter.py` only.

## How to add a new gate

This is the most common extension. Worked example — the `perf` gate added exactly this way:

1. **Write `area/verify/<gate>.py`** with `<gate>_verify(name, *, backend="acp", model=None, strict=False, …) -> bool`.
   Return `True` on pass **or when advisory/unmeasurable**, `False` only on a blocking
   breach. Mirror `nfr.py` for a deterministic budget gate, or `chaos.py`/`product.py`
   for an agent-driven one. Accept `backend`/`model` even if unused (dispatch uniformity).
2. **Export it** from `area/verify/__init__.py`.
3. **Wire the CLI** in `area/cli.py` — the gate set is a single source, `_GATE_ORDER`:
   - add the gate name to **`_GATE_ORDER`** (this alone puts it in the `_finish`
     selection and the `--all` help, which are generated from it);
   - add a `"<gate>": lambda: <gate>_verify(name, …)` entry to the **`runners`** dict
     in `_run_gate` (forward its distinctive kwargs there);
   - add `--<gate>` (and any options) in `_add_common` (and the `iterate` parser);
   - optionally a standalone `area <gate> <name>` subcommand + handler + `_HANDLERS`.
4. **Test it** (`tests/test_<gate>.py`): the pure helpers, the pass/fail/advisory/skip
   verdicts (monkeypatch the measurement so no real app is needed), and `_run_gate`
   dispatch. `tests/test_gate_registry.py` already asserts every `_GATE_ORDER` gate
   dispatches + that `--all` lists it, so a missing `runners` entry fails CI.
   Keep it `mypy --strict` clean — the whole `area` package is fully strict-typed.
5. **Dogfood it** against a real built app before trusting it — live runs flush out bugs
   unit tests can't (every gate fix this repo has shipped was found that way).

## How to add an engine backend

All agent execution goes through [`area/engine/adapter.py`](area/engine/adapter.py).
Add the backend there behind `build_agent(backend, model=…)` and keep `run_until`
/`run_once`'s contract (it logs `outer_iters`/cost to `area/obs.py`). Nothing else in
the codebase should import the SDK directly.

## Workspace & naming

Generated apps live in gitignored `workspace/apps/<name>` (+ `workspace/specs/<name>`).
To keep them OUT of the repo entirely (isolation, lean checkout), set
**`AREA_WORKSPACE`** to an external dir before running `area`
(e.g. `export AREA_WORKSPACE=~/area-generated`); all generated apps/specs/.area
telemetry then live there instead. The path layout is defined once in
[`area/paths.py`](area/paths.py).
A product name is required — the CLI prompts for it interactively and errors
non-interactively, and won't silently overwrite an existing product. Don't commit
anything under `workspace/`.

## Releases

Pre-1.0, [SemVer](https://semver.org/). A release: move the relevant
`## [Unreleased]` notes in [`CHANGELOG.md`](CHANGELOG.md) under a new
`## [x.y.z] — DATE` heading, commit, then tag `git tag vx.y.z && git push --tags`.
Bump **minor** for new capabilities (a new gate, flow, or command), **patch** for
fixes, and reserve **major** for a breaking change to the CLI/flags, the spec
format, or the oracle-loop contract. Generated apps are not versioned with the
factory — each is exported as its own repo.

## Commits & PRs

- One logical change per commit, with a test. Explain *why* in the body, not just *what*.
- Branch off `main`; the SaaS coordinator/runner work lives on `saas-coordinator-runner`.
- End commit messages with the attribution line the project uses
  (`Co-Authored-By: …`), and PR descriptions with the generated-with line.
- Prefer dogfooding a change on a real app over claiming it works from logic alone —
  "oracle green" is the bar, and *logic-green ≠ live-works* (the e2e gate exists because
  of exactly that lesson).
