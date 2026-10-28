"""area.verify — holdout acceptance verification (anti self-certification).

PLAN §1 warns: do not let the implementing LLM certify itself by writing the
tests it must pass. `area/build` lets the agent write its own quick tests to
iterate — fine for getting something working, but NOT a trustworthy "done".

This module adds an INDEPENDENT acceptance oracle:
  1. a separate VERIFIER agent writes acceptance tests from acceptance.yaml,
  2. those tests are CHECKSUM-LOCKED under __tests__/_holdout/,
  3. the oracle rejects any run where the holdout files changed.

Two ways to use it:
- **Post-build gate** (`holdout_verify`): build first (agent's own tests), then
  an independent suite is authored + a FIXER agent makes it pass editing APP
  CODE ONLY. "Done" = an independently-authored, unmodified suite passes.
- **TDD, tests-first** (`author_and_lock` + `tdd_build_oracle`): author + lock
  the independent suite BEFORE build (the "red" step), then the BUILD loop's
  oracle IS that locked suite. This fuses TDD with anti-self-certification: the
  build is driven by tests the implementer never wrote and cannot touch.
"""
from __future__ import annotations

import hashlib
import os
import re
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import yaml

from area._util import safe_name
from area.engine import (
    Backend, Verifier, VerifyResult, build_agent, run_once, run_until, scrubbed_env,
)
from area.paths import WORKSPACE  # noqa: E402 (leaf single-source; avoids importing the whole pipeline+SDK behind a gate)
from area.verify._runners import assert_locked_files_ran, assert_vitest_ran

HOLDOUT_DIR = "__tests__/_holdout"
# The ONE file the builder may write inside the locked dir: a challenge that a
# locked test is wrong. It is never executed (not a test) and is excluded from
# the lock, so raising it is sanctioned, not "tampering". An independent
# verifier — never the builder — adjudicates it (see `readjudicate`).
CHALLENGE_FILE = "_CHALLENGE.md"


def _lock(holdout: Path) -> dict[str, str]:
    return {
        str(f.relative_to(holdout)): hashlib.sha256(f.read_bytes()).hexdigest()
        for f in sorted(holdout.rglob("*"))
        if f.is_file() and f.name != CHALLENGE_FILE
    }


def _expected_ac_count(holdout: Path) -> int:
    """Distinct AC-<n> ids across the holdout test files = how many acceptance
    criteria the suite must execute (≥1 test per AC), used to reject a green
    exit that actually ran too few / zero tests."""
    ids: set[str] = set()
    for f in holdout.rglob("*"):
        if f.is_file() and f.suffix in {".ts", ".tsx", ".js", ".jsx", ".mjs"}:
            ids |= set(re.findall(r"\bAC-\d+\b", f.read_text(errors="ignore")))
    return len(ids)


# Wall clock for one holdout test run.
_TEST_TIMEOUT_S = 1800.0


def _lock_file(app: Path) -> Optional[Path]:
    """The on-disk lock path for a standard workspace/apps/<name> layout, else None."""
    if app.parent.name != "apps":
        return None  # non-standard layout (e.g. a temp clone dir)
    return app.parent.parent / "specs" / app.name / "holdout.lock"


def _persist_lock(app: Path) -> None:
    """Persist the on-disk holdout.lock via the canonical tools/lock-holdout.sh, so
    a --tdd/author-locked holdout is recognized by tools/verify-holdout-intact.sh
    AND the PreToolUse guard hook — not only a hand-locked one. The --tdd pipeline
    otherwise keeps the checksum in memory only. Best-effort: a failure here never
    breaks the build (the in-memory lock in _holdout_oracle still guards it)."""
    if _lock_file(app) is None:
        return
    script = Path(__file__).resolve().parents[2] / "tools" / "lock-holdout.sh"
    if not script.exists():
        return
    try:
        subprocess.run(["bash", str(script), app.name, str(app.parent.parent)],
                       capture_output=True, text=True, timeout=30)
    except Exception:  # noqa: BLE001
        pass


def _clear_lock(app: Path) -> None:
    """Remove the on-disk lock (before a sanctioned re-authoring) so the guard hook
    can't block the independent verifier from correcting a challenged test."""
    lf = _lock_file(app)
    try:
        if lf is not None and lf.exists():
            lf.unlink()
    except OSError:
        pass


def _parity_preamble(reference: str) -> str:
    return (
        "=== CLONE PARITY MODE ===\n"
        "This is a CLONE of a reference app — 'correct' means BEHAVIORAL PARITY "
        "with it, not just generic criteria. Reference:\n"
        f"  {reference}\n"
        "The reverse-engineer stage may have cloned its source into ./_sample/ "
        "(read it if present). Ground EACH acceptance test in the reference's "
        "OBSERVED behavior — concrete input -> output examples you can evidence "
        "from it — so that passing the suite means the clone reproduces the "
        "original's behavior. Do not invent behavior the reference does not show.\n\n"
    )


def _author_prompt(acc_yaml: str, *, tdd: bool, reference: Optional[str] = None) -> str:
    parity = _parity_preamble(reference) if reference else ""
    # In parity mode the ONE thing the agent may read is the reference (./_sample).
    may_read = "Read ./_sample/ (the reference) if present, but " if reference else ""
    if tdd:
        # TDD: the app does NOT exist yet, so the tests DEFINE the contract the
        # implementation must satisfy (import paths + function signatures).
        return (
            parity
            + "You are an INDEPENDENT acceptance verifier (NOT the implementer). "
            "This is TEST-DRIVEN DEVELOPMENT and you are in an EMPTY project "
            "directory. Your ONLY job, RIGHT NOW, is to CREATE test files — "
            f"{may_read}do NOT look for or read existing app/source code (there is "
            "none yet), do NOT scaffold the app, do NOT create package.json, do "
            "NOT explore unrelated directories, do NOT explain. Start writing "
            "files immediately.\n"
            f"Under {HOLDOUT_DIR}/ write Vitest acceptance tests that assert EACH "
            "acceptance criterion below AND, in doing so, DEFINE the module "
            "contract the implementation must satisfy: import from stable, "
            "predictable paths (e.g. `../../lib/<entity>`) and call explicitly "
            "named functions with explicit argument/return shapes. One `describe` "
            "per AC (tag it AC-<id>), strict and faithful to the spec. Also write "
            f"a short {HOLDOUT_DIR}/CONTRACT.md listing every module path and "
            "function signature your tests import. Create files ONLY under "
            f"{HOLDOUT_DIR}/. After writing, STOP.\n\n"
            f"=== acceptance.yaml ===\n{acc_yaml}"
        )
    return (
        parity
        + "You are an INDEPENDENT acceptance verifier (NOT the implementer). "
        f"Write Vitest acceptance tests under {HOLDOUT_DIR}/ that assert EACH "
        "acceptance criterion below against the app's REAL modules (import its "
        "lib/domain functions as the app exposes them). One `describe` per AC, "
        "strict and faithful. Do NOT modify any app source code — ONLY create "
        f"test files under {HOLDOUT_DIR}/. After writing, STOP.\n\n"
        f"=== acceptance.yaml ===\n{acc_yaml}"
    )


def _app_has_source(app: Path) -> bool:
    """Is there already an implementation for an author agent to read?"""
    for sub in ("lib", "app", "src", "components", "server", "pages"):
        d = app / sub
        if d.is_dir() and any(d.rglob("*")):
            return True
    return False


def _has_tests(holdout: Path) -> bool:
    return any(holdout.rglob("*.ts")) or any(holdout.rglob("*.js"))


def _ac_ids(acc_yaml: str) -> list[str]:
    try:
        data = yaml.safe_load(acc_yaml) or {}
        return [str(c["id"]) for c in data.get("criteria", []) if c.get("id")]
    except Exception:
        return []


def _test_text(holdout: Path) -> str:
    out = []
    for f in sorted(holdout.rglob("*")):
        if f.is_file() and f.suffix.lower() in (".ts", ".tsx", ".js", ".jsx"):
            try:
                out.append(f.read_text(errors="ignore"))
            except OSError:
                pass
    return "\n".join(out)


def _fingerprint(holdout: Path) -> frozenset[tuple[str, str]]:
    # Key on CONTENT hash, not st_size: a rewrite with the same byte length (common
    # when an author iterates) must count as progress, not trip the stall detector.
    return frozenset(
        (str(f.relative_to(holdout)), hashlib.sha256(f.read_bytes()).hexdigest())
        for f in holdout.rglob("*")
        if f.is_file()
    )


def _authoring_oracle(
    holdout: Path, acc_yaml: str, *, require_contract: bool, strict: bool = False
) -> tuple[bool, str]:
    """Quality gate on the authored suite (not just 'a file exists').

    Checks, in order of severity: tests exist, a CONTRACT.md exists (TDD),
    every acceptance criterion id is covered, and assertions are present.
    Returns (ok, specific-feedback). Pure + deterministic — no agent, no npm.
    """
    problems: list[str] = []
    if not _has_tests(holdout):
        return False, (
            f"No Vitest test file exists under {HOLDOUT_DIR}/. Create the .test.ts "
            "files now — write files, do not explore the repo."
        )
    text = _test_text(holdout)
    if require_contract and not (holdout / "CONTRACT.md").exists():
        problems.append(
            f"Missing {HOLDOUT_DIR}/CONTRACT.md — list every module path + function "
            "signature your tests import."
        )
    missing = [
        ac for ac in _ac_ids(acc_yaml)
        if not re.search(rf"\b{re.escape(ac)}\b", text)
    ]
    if missing:
        problems.append(
            "These acceptance criteria are NOT covered by any test (add one "
            f"`describe`/`it` each, tagged with the id): {', '.join(missing)}."
        )
    if "expect(" not in text and "assert" not in text:
        problems.append(
            "The tests contain no assertions (`expect(...)`) — they must assert "
            "concrete outcomes, not be empty."
        )
    # ORACLE STRENGTH. Everything above measures whether a test EXISTS for each
    # criterion; this measures whether it can SETTLE it. `expenses` AC-14 declared a
    # runtime property ("makes no outbound network requests") and was "verified" by
    # grepping source — it reported PASS while telemetry was enabled. The verdict is
    # reported either way and BLOCKS only under --strict, because an approximating
    # oracle is a legitimate choice as long as it is labelled; failing every app with
    # one hard-to-observe criterion would be a false block, not a finding.
    weak = _weak_criteria(acc_yaml, text)
    if weak:
        msg = (
            f"These criteria declare `verify_by: execution` — a claim about the "
            f"RUNNING system — but their tests only read the source, so a PASS would "
            f"not mean the property holds: {', '.join(weak)}. Drive the app through "
            f"its public surface (import ../../lib/...) and assert the observed "
            f"behaviour, or change the criterion's `verify_by`/`then` to something "
            f"inspection can actually settle."
        )
        if strict:
            problems.append(msg)
        else:
            print(f"[holdout] ⚠ oracle strength: {msg}")
    return (not problems), " ".join(problems)


def _weak_criteria(acc_yaml: str, test_text: str) -> list[str]:
    """Criteria whose test cannot settle the claim they make (area.verify.strength)."""
    from area.verify.strength import classify, weak

    try:
        data = yaml.safe_load(acc_yaml) or {}
        crit = data.get("criteria") or [] if isinstance(data, dict) else []
    except Exception:  # noqa: BLE001
        return []
    return weak(classify([c for c in crit if isinstance(c, dict)], test_text))


def _locked_state(app: Path) -> str:
    """"none" | "intact" | "tampered" — via the CANONICAL checker, so this cannot
    drift from `tools/verify-holdout-intact.sh` or duplicate its hash format."""
    lf = _lock_file(app)
    if lf is None or not lf.exists():
        return "none"
    script = Path(__file__).resolve().parents[2] / "tools" / "verify-holdout-intact.sh"
    if not script.exists():
        return "none"
    try:
        r = subprocess.run(["bash", str(script), app.name, str(app.parent.parent)],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return "none"
    return {0: "intact", 1: "tampered"}.get(r.returncode, "none")


def author_until(
    app: Path, acc_yaml: str, *, backend: Backend, model: Optional[str], tdd: bool,
    reference: Optional[str] = None, attempts: int = 4, max_no_progress: int = 2,
    strict: bool = False,
) -> tuple[Path, dict[str, str]]:
    """Author the holdout suite under its OWN oracle-loop.

    On the keyless ACP backend we cannot strip the agent's terminal, so the
    verifier may wander (explore instead of write). Instead of trusting a single
    shot, we gate the OUTPUT with `_authoring_oracle` and re-prompt with its
    SPECIFIC feedback (a just-in-time reminder) until the suite is complete —
    with a no-progress detector and a recorded stop reason as backstops.
    """
    holdout = app / HOLDOUT_DIR
    holdout.mkdir(parents=True, exist_ok=True)

    # NEVER re-author over an already-locked oracle.
    #
    # This used to run unconditionally, and `run_once` fires BEFORE the authoring
    # oracle is consulted — so `area verify <app>` on a --tdd-built app invoked an
    # author agent in a directory that already held the locked holdout, let it rewrite
    # those files, then `_persist_lock` rewrote the lock to match. A strong oracle
    # authored pre-build FROM THE SPEC ONLY was silently replaced by one authored
    # post-build against the implementation it could read — and because the lock was
    # rewritten too, `tools/verify-holdout-intact.sh` then reported
    # "✅ oracle độc lập được giữ". The tamper detector confirmed independence at the
    # exact moment independence was lost. Proven with a stubbed agent.
    #
    # Replacing a locked oracle has exactly ONE sanctioned path: `readjudicate`, which
    # clears the lock first after an independent verifier upholds a `_CHALLENGE.md`.
    state = _locked_state(app)
    if state == "intact":
        print(f"[area] holdout: REUSING the locked oracle under {HOLDOUT_DIR}/ "
              "(authored earlier and checksum-locked — not re-authoring it)")
        return holdout, _lock(holdout)
    if state == "tampered":
        raise RuntimeError(
            f"{HOLDOUT_DIR}/ no longer matches its lock — the oracle was modified. "
            "Revert it to the locked version and fix the IMPLEMENTATION instead; if a "
            f"test is genuinely wrong, write {CHALLENGE_FILE} so an independent "
            "verifier can re-adjudicate and re-lock it."
        )
    if not tdd and _app_has_source(app):
        print("[area] ⚠ holdout: authoring the oracle AFTER the implementation exists. "
              "It must import the app's real modules, so it cannot be authored from "
              "the spec ONLY — a weaker oracle than a --tdd build's pre-locked "
              "holdout. Prefer `--tdd`.")

    label = "holdout:author" + (":tdd" if tdd else "") + (":parity" if reference else "")
    base = _author_prompt(acc_yaml, tdd=tdd, reference=reference)

    prev_fp: Optional[frozenset[tuple[str, str]]] = None
    stalls = 0
    stop = "exhausted attempts"
    feedback = ""
    for attempt in range(1, attempts + 1):
        prompt = base if attempt == 1 else (
            "Your previous attempt did not finish the suite. Fix EXACTLY this, by "
            f"writing files under {HOLDOUT_DIR}/ now — do not explore other "
            f"directories, do not explain:\n{feedback}\n\n" + base
        )
        vagent = build_agent(backend, model=model)
        try:
            run_once(vagent, app, prompt, label=label)
        finally:
            vagent.close()

        ok, feedback = _authoring_oracle(holdout, acc_yaml, require_contract=tdd, strict=strict)
        if ok:
            stop = "ok"
            break
        fp = _fingerprint(holdout)
        if fp == prev_fp:
            stalls += 1
            if stalls >= max_no_progress:
                stop = f"no progress for {stalls} attempts"
                break
        else:
            stalls = 0
        prev_fp = fp
        print(f"[area] holdout: author attempt {attempt}/{attempts} not complete "
              f"— {feedback[:140]}")

    ok, feedback = _authoring_oracle(holdout, acc_yaml, require_contract=tdd, strict=strict)
    if not ok:
        raise RuntimeError(
            f"holdout authoring failed ({stop}) after {attempts} attempts: {feedback}"
        )
    lock = _lock(holdout)
    _persist_lock(app)  # write workspace/specs/<name>/holdout.lock (hook + verify-intact)
    print(f"[area] holdout: locked {len(lock)} file(s) under {HOLDOUT_DIR}/ "
          f"(all {len(_ac_ids(acc_yaml))} AC covered)")
    return holdout, lock


def _vitest_shell(report: Path, build: Optional[str] = None) -> list[str]:
    """The holdout runner command. `--reporter=json` into `report` is what lets the
    oracle check WHICH files ran, not just how many tests passed; `--reporter=default`
    is kept alongside it so the agent still gets readable failure output. `report`
    lives OUTSIDE the app under a per-run random name, so the builder can neither
    predict nor pre-write it."""
    tests = (f"npx vitest run {HOLDOUT_DIR} --reporter=default --reporter=json "
             f"--outputFile.json={shlex.quote(str(report))}")
    return ["bash", "-lc", f"{build} && {tests}" if build else tests]


def _holdout_oracle(
    app: Path, holdout: Path, lock: dict[str, str], *,
    cmd: Optional[list[str]] = None, build: Optional[str] = None,
) -> Verifier:
    """A Verifier that (1) rejects any change to the locked suite, then (2) runs it
    and confirms the LOCKED FILES THEMSELVES executed.

    `build` prefixes a production build onto the run (TDD mode). `cmd` replaces the
    whole command and is a test seam only — it skips the executed-files check, because
    there is no vitest report to read.
    """
    expected = _expected_ac_count(holdout)

    def oracle() -> VerifyResult:
        if _lock(holdout) != lock:
            return VerifyResult(
                False,
                f"FORBIDDEN: files under {HOLDOUT_DIR}/ were modified. Those are "
                "the locked acceptance tests — revert them and fix APP CODE only.",
            )
        # A fresh, unpredictable report path per attempt: a stale or planted file
        # must not be able to vouch for a run that never happened.
        report: Optional[Path] = None
        if cmd is not None:
            test_cmd = cmd
        else:
            fd, tmp = tempfile.mkstemp(prefix="area-holdout-", suffix=".json")
            os.close(fd)
            report = Path(tmp)
            report.unlink(missing_ok=True)  # must be CREATED by the run, not found
            test_cmd = _vitest_shell(report, build)
        try:
            # Capped: an unbounded oracle run can hang the whole build (same gap
            # closed in area.engine.adapter.command_verifier).
            # `env=scrubbed_env()`: this runs the GENERATED app's test suite (and in
            # TDD mode its `npm install` + production build), i.e. agent-authored code
            # with arbitrary postinstall scripts. It must not inherit the deploy/cloud
            # tokens this process holds.
            proc = subprocess.run(test_cmd, cwd=str(app), capture_output=True,
                                  text=True, timeout=_TEST_TIMEOUT_S,
                                  env=scrubbed_env())
        except subprocess.TimeoutExpired:
            # TimeoutExpired is a SubprocessError, NOT an OSError — without this it
            # would escape the oracle and crash the build loop.
            return VerifyResult(False, (
                f"holdout runner TIMED OUT after {_TEST_TIMEOUT_S:.0f}s — the locked "
                "suite did not finish (a hung test or watch mode?)"))
        except OSError as e:
            return VerifyResult(False, f"holdout runner failed: {e}")
        out = (proc.stdout + "\n" + proc.stderr).strip()
        if proc.returncode != 0:
            return VerifyResult(False, out[-4000:])
        # Exit 0 is NOT enough: confirm the locked suite actually RAN (the app's
        # vitest config is builder-controlled + unlocked, so passWithNoTests / a
        # non-matching include can exit 0 with zero tests collected).
        ran, why = assert_vitest_ran(out, expected)
        if ran and report is not None:
            # Counting passes is not enough. vitest's positional filter is a SUBSTRING
            # match and only narrows what `include`/`exclude` globbed, so a builder-
            # authored `exclude` for the locked dir plus a decoy directory whose name
            # contains it (`__tests__/_holdout_decoy/`) yields exit 0 with the locked
            # tests never collected. Confirm the locked files ran, by name.
            # lock keys are relative to the HOLDOUT dir, not the app root.
            ran, why = assert_locked_files_ran(report, holdout, lock.keys())
        if report is not None:
            report.unlink(missing_ok=True)
        if not ran:
            return VerifyResult(
                False,
                f"ORACLE DID NOT RUN: build/exit was green but {why}. The locked "
                f"acceptance suite must EXECUTE — do not exclude, rename or shadow "
                f"{HOLDOUT_DIR}/ in the vitest config; fix APP CODE instead.\n\n"
                + out[-3500:],
            )
        return VerifyResult(True, out[-4000:])

    return oracle


# --- TDD, tests-first API (used by the pipeline when --tdd is set) ------------

def author_and_lock(
    name: str,
    *,
    backend: Backend = "acp",
    model: Optional[str] = None,
    acc_yaml: Optional[str] = None,
    app: Optional[str | Path] = None,
    reference: Optional[str] = None,
    strict: bool = False,
) -> tuple[Path, dict[str, str]]:
    """TDD 'red' step: author + checksum-lock the holdout suite BEFORE any build.

    Returns (holdout_dir, lock). The app dir may be otherwise empty — the suite
    defines the contract the subsequent build must satisfy. Pass `app` to target
    a non-default workspace (otherwise WORKSPACE/apps/<name>). Pass `reference`
    (a clone's source) to author tests that assert BEHAVIORAL PARITY with it.
    """
    name = safe_name(name)
    app = Path(app) if app else WORKSPACE / "apps" / name
    app.mkdir(parents=True, exist_ok=True)
    if acc_yaml is None:
        acc_path = WORKSPACE / "specs" / name / "acceptance.yaml"
        if not acc_path.exists():
            raise RuntimeError(f"no acceptance.yaml at {acc_path}")
        acc_yaml = acc_path.read_text()
    return author_until(
        app, acc_yaml, backend=backend, model=model, tdd=True, reference=reference, strict=strict)


def tdd_build_oracle(
    app: str | Path, holdout: Path, lock: dict[str, str], *, target: str = "cloudflare"
) -> Verifier:
    """The BUILD loop's oracle in --tdd mode: production build is green AND the
    locked holdout suite passes AND the locked files are untouched."""
    app = Path(app)
    build = "npm run build:cf" if target == "cloudflare" else "npm run build"
    prefix = f"[ -d node_modules ] || npm install --no-audit --no-fund; {build}"
    return _holdout_oracle(app, holdout, lock, build=prefix)


def pending_challenge(holdout: Path) -> Optional[str]:
    """Return the text of an unresolved builder challenge, if any.

    A challenge the independent verifier already rejected starts with 'REJECTED'
    and is treated as resolved (no re-adjudication).
    """
    f = holdout / CHALLENGE_FILE
    if not f.exists():
        return None
    text = f.read_text(errors="ignore").strip()
    if not text or text.upper().startswith("REJECTED"):
        return None
    return text


def readjudicate(
    app: str | Path,
    holdout: Path,
    acc_yaml: str,
    *,
    backend: Backend = "acp",
    model: Optional[str] = None,
) -> tuple[bool, dict[str, str]]:
    """Escape hatch for a WRONG locked test (evolving-tests-under-governance).

    The builder cannot edit locked tests; if it believes one is wrong it raises
    a `_CHALLENGE.md`. Here an INDEPENDENT verifier (never the implementer)
    adjudicates that challenge against acceptance.yaml:
      - valid   -> it corrects ONLY the disputed test to match the spec,
      - invalid -> it leaves tests unchanged and writes 'REJECTED: <why>'.
    Either way the suite is RE-LOCKED. Returns (tests_changed, new_lock).
    """
    app = Path(app)
    challenge = pending_challenge(holdout)
    if challenge is None:
        return False, _lock(holdout)
    before = _lock(holdout)
    # This is the sanctioned path for CORRECTING a challenged locked test. Clear
    # the on-disk lock first so the guard hook can't block the independent
    # verifier's edit; the suite is re-locked (and re-persisted) below.
    _clear_lock(app)
    task = (
        "You are the INDEPENDENT acceptance verifier (NOT the implementer). The "
        f"builder challenges the locked tests under {HOLDOUT_DIR}/ as wrong. "
        "Adjudicate STRICTLY against the acceptance criteria below.\n"
        "- If the challenge is VALID (a test contradicts the spec or is "
        "impossible), correct ONLY the disputed test so it faithfully matches "
        "the spec. Do NOT weaken coverage to make the app pass.\n"
        "- If the challenge is INVALID, change NO test and overwrite "
        f"{HOLDOUT_DIR}/{CHALLENGE_FILE} with a single line 'REJECTED: <reason>'.\n"
        f"Touch only files under {HOLDOUT_DIR}/. After deciding, STOP.\n\n"
        f"=== builder challenge ===\n{challenge}\n\n"
        f"=== acceptance.yaml ===\n{acc_yaml}"
    )
    agent = build_agent(backend, model=model)
    try:
        run_once(agent, app, task, label="holdout:readjudicate")
    finally:
        agent.close()
    after = _lock(holdout)
    _persist_lock(app)  # re-persist the (possibly corrected) locked suite
    changed = after != before
    print(
        f"[area] holdout: re-adjudicated challenge -> "
        f"{'tests CORRECTED + re-locked' if changed else 'challenge REJECTED (tests stand)'}"
    )
    return changed, after


# --- Post-build gate API (unchanged behavior) --------------------------------

def holdout_verify(
    name: str,
    *,
    backend: Backend = "acp",
    model: Optional[str] = None,
    max_iters: int = 3,
) -> bool:
    """Independently verify a built app against its acceptance criteria.

    Returns True only if an independently-authored, unmodified holdout test
    suite passes. Raises if there is no app/spec.
    """
    name = safe_name(name)
    app = WORKSPACE / "apps" / name
    acc_path = WORKSPACE / "specs" / name / "acceptance.yaml"
    if not app.exists():
        raise RuntimeError(f"no app at {app}")
    if not acc_path.exists():
        raise RuntimeError(f"no acceptance.yaml at {acc_path}")

    holdout, lock = author_until(
        app, acc_path.read_text(), backend=backend, model=model, tdd=False
    )
    oracle = _holdout_oracle(app, holdout, lock)

    # Already passing? (the honest, best case)
    if oracle().ok:
        print("[area] holdout: PASS on first check (app already satisfies ACs)")
        return True

    # FIXER agent: make holdout pass, APP CODE ONLY (holdout locked)
    ftask = (
        f"Independent acceptance tests under {HOLDOUT_DIR}/ are FAILING. Fix the "
        f"APP CODE so they pass. You MUST NOT edit, delete, rename, or weaken "
        f"anything under {HOLDOUT_DIR}/ — they are locked acceptance tests. "
        f"Check with `npx vitest run {HOLDOUT_DIR}`."
    )
    fagent = build_agent(backend, model=model)
    try:
        passed, _ = run_until(
            fagent, app, ftask, oracle, max_iters=max_iters, label="holdout:fix"
        )
    finally:
        fagent.close()
    print(f"[area] holdout: {'PASS' if passed else 'FAIL'}")
    return passed
