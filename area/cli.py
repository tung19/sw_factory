"""area CLI.

    area run   "<requirement>" [--name N] [--target cloudflare|plain] [--deploy]
    area clone "<git-url|path|http-url>" [--name N] [--kind auto|repo|path|url]
                                         [--target ...] [--deploy]
    area deploy <name> [--yes]

Common: [--backend acp|llm] [--model M] [--spec-iters K] [--build-iters K] [--yes]
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

from area._util import safe_name

if TYPE_CHECKING:
    from area.inception.engine import ApproveFn, Bolt
    from area.pipeline import PipelineResult

# The post-build gates, in run order — the SINGLE source for the gate set. The
# `_finish` selection, `_run_gate` dispatch, and the `--all` help string all derive
# from this, so adding a gate can't drift one of them (a lesson from CONTRIBUTING's
# "a gate change without a test silently drifts"). A test asserts _run_gate covers
# every name here.
_GATE_ORDER = ("verify", "audit", "e2e", "chaos", "nfr", "perf", "visual",
               "product", "cost")
_ALL_GATES_HELP = "run all gates: " + " + ".join(_GATE_ORDER)


def _slug_from(text: str, fallback: str) -> str:
    """A short kebab-case slug suggestion from a requirement/source string."""
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    slug = "-".join(words[:4])[:40].strip("-")
    return slug or fallback


def _resolve_name(provided: str | None, *, hint: str, fallback: str) -> str:
    """Resolve the product name. Each product gets its OWN workspace/apps/<name>
    (+ specs/<name>), so a name is required — AREA never silently dumps builds into
    a shared generic folder. If --name is omitted: prompt interactively (suggesting
    a slug from the requirement); non-interactive → fail with guidance."""
    if provided:
        return safe_name(provided)
    suggestion = _slug_from(hint, fallback)
    if sys.stdin.isatty():
        try:
            ans = input(f"Tên sản phẩm cho project này [{suggestion}]: ").strip()
        except EOFError:
            ans = ""
        return safe_name(ans or suggestion)
    print(f"[area] --name là BẮT BUỘC khi chạy không tương tác — mỗi sản phẩm cần "
          f"workspace riêng (workspace/apps/<name>). Gợi ý: --name {suggestion}")
    raise SystemExit(2)


def _check_collision(name: str) -> str:
    """Don't silently clobber an existing product folder. Interactive: confirm
    overwrite, take a new name, or bail to `area iterate`. Non-interactive: warn
    and proceed (the caller chose the name explicitly)."""
    from area.pipeline import WORKSPACE

    while True:
        app_dir = WORKSPACE / "apps" / name
        if not (app_dir.exists() and any(app_dir.iterdir())):
            return name
        if not sys.stdin.isatty():
            print(f"[area] ⚠ '{name}' đã tồn tại (workspace/apps/{name}) — sẽ build "
                  f"ĐÈ. Để sửa dần dùng: area iterate {name} \"<thay đổi>\"")
            return name
        try:
            ans = input(f"[area] '{name}' đã tồn tại. [o] ghi đè · [Enter] đổi tên · "
                        "[i] iterate? ").strip().lower()
        except EOFError:
            ans = "o"
        if ans == "o":
            return name
        if ans == "i":
            print(f"[area] → chạy: area iterate {name} \"<thay đổi>\"")
            raise SystemExit(0)
        try:
            nn = input("Tên mới: ").strip()
        except EOFError:
            nn = ""
        if nn:
            name = safe_name(nn)


def _looks_auth(spec_dir: Path) -> bool:
    """Does the spec describe auth / sessions / forms? Those are exactly the apps
    where logic-green ≠ live-works (a holdout can pass while live signup is broken),
    so the e2e gate is enforced before a deploy of such an app."""
    text = ""
    for fn in ("spec.yaml", "acceptance.yaml"):
        p = Path(spec_dir) / fn
        if p.exists():
            text += p.read_text(errors="ignore").lower()
    return bool(re.search(
        r"\b(auth|login|log ?in|sign ?in|sign ?up|signup|register|password|"
        r"session|cookie|credential|logout|form|submit)\b", text))


def _confirm_fn(assume_yes: bool) -> Callable[[str], bool]:
    """The deploy human gate. The argument is a DESCRIPTION of what is about to
    happen (built by area.deploy._gate_description) — the old prompt hardcoded
    "Cloudflare PRODUCTION" for every provider and never said that a production
    database would be created and migrated."""
    def confirm(what: str) -> bool:
        if assume_yes:
            return True
        try:
            ans = input(f"Deploy {what}? [y/N] ").strip().lower()
        except EOFError:
            return False
        return ans == "y"

    return confirm


def _edit_via_editor(text: str, filename: str) -> str:
    """Open $EDITOR on the proposed text and return the edited result; if no editor
    is configured, accept as-is."""
    import subprocess
    import tempfile

    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if not editor:
        print("[area] (no $EDITOR set — accepting as-is)")
        return text
    with tempfile.NamedTemporaryFile("w+", suffix="-" + filename, delete=False) as tf:
        tf.write(text)
        path = tf.name
    try:
        subprocess.run([*editor.split(), path])
        with open(path) as f:
            return f.read()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _inception_approver(assume_yes: bool) -> "ApproveFn":
    """A human-governance approve callback for `area inception`: show each proposed
    bolt and let the human accept / edit / regenerate (or auto-accept with --yes
    / non-interactive)."""
    from area.inception.engine import REGENERATE

    def approve(bolt: "Bolt", proposed: str) -> object:
        print(f"\n[area] ─── {bolt.title} ({bolt.filename}) — đề xuất ───\n{proposed}\n")
        if assume_yes or not sys.stdin.isatty():
            print(f"[area] tự chấp nhận {bolt.filename}"
                  + (" (--yes)" if assume_yes else " (không tương tác)"))
            return proposed
        while True:
            try:
                ans = input(f"[{bolt.title}] [a] chấp nhận · [e] sửa · [r] tạo lại? ").strip().lower()
            except EOFError:
                return proposed
            if ans in ("", "a"):
                return proposed
            if ans == "r":
                return REGENERATE
            if ans == "e":
                return _edit_via_editor(proposed, bolt.filename)

    return approve


def _add_agent_opts(sp: argparse.ArgumentParser) -> None:
    """The agent knobs shared by the standalone gate subcommands (verify/e2e/
    audit/chaos): which backend/model, and the retry/cost caps."""
    sp.add_argument("--backend", default="acp", choices=["acp", "llm"])
    sp.add_argument("--model", default=None)
    sp.add_argument("--max-iters", type=int, default=3)
    sp.add_argument("--budget", type=float, default=None)
    sp.add_argument("--agent-iters", type=int, default=None)


def _add_common(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--name", default=None, help="project name / output folder")
    sp.add_argument("--target", default="cloudflare", choices=["cloudflare", "vercel", "plain"])
    sp.add_argument("--backend", default="acp", choices=["acp", "llm"])
    sp.add_argument("--model", default=None)
    sp.add_argument("--spec-iters", type=int, default=3)
    sp.add_argument("--build-iters", type=int, default=3)
    sp.add_argument("--budget", type=float, default=None,
                    help="max USD spend per agent run (cost cap)")
    sp.add_argument("--agent-iters", type=int, default=None,
                    help="max steps per agent run (default 80)")
    sp.add_argument("--design", dest="design", action="store_const", const=True, default=None,
                    help="force the architect stage (design.md) before build "
                         "(default: AUTO for a non-trivial app)")
    sp.add_argument("--no-design", dest="design", action="store_const", const=False,
                    help="skip the architect stage even for a non-trivial app")
    sp.add_argument("--tdd", action="store_true",
                    help="TDD: lock independent acceptance tests BEFORE build; "
                         "the build oracle IS that locked suite (implies verify)")
    sp.add_argument("--expect", default=None,
                    help="expected results / examples — authoritative, become "
                         "acceptance criteria (you supply part of the oracle)")
    sp.add_argument("--expect-file", default=None,
                    help="file containing expected results / examples")
    sp.add_argument("--clarify", dest="clarify", action="store_true", default=True,
                    help="(DEFAULT) stop at spec and surface MATERIAL ambiguities "
                         "before building, instead of guessing silently")
    sp.add_argument("--no-clarify", dest="clarify", action="store_false",
                    help="skip the clarify gate — guess defaults and build without "
                         "asking (NOT recommended for a vague requirement). The "
                         "independent spec reviewer still RUNS and records what it "
                         "finds; use --no-spec-review to skip that too")
    sp.add_argument("--spec-review", dest="spec_review", action="store_true", default=True,
                    help="(DEFAULT) an INDEPENDENT reviewer hunts for material "
                         "ambiguities the spec stage missed, to surface via --clarify")
    sp.add_argument("--no-spec-review", dest="spec_review", action="store_false",
                    help="skip the independent spec-vs-intent reviewer")
    sp.add_argument("--verify", action="store_true",
                    help="independent holdout acceptance check after a green build")
    sp.add_argument("--audit", action="store_true", help="security/static gate after build")
    sp.add_argument("--audit-level", default="high", choices=["low", "moderate", "high", "critical"],
                    help="npm-audit severity threshold for the deterministic tier-1 gate")
    sp.add_argument("--strict", action="store_true",
                    help="audit tier-2: make advisory risky-pattern findings BLOCK")
    sp.add_argument("--no-block-injection", action="store_true",
                    help="downgrade the injection-class audit findings (XSS/eval/SQL-"
                         "injection, which BLOCK by default) to advisory")
    sp.add_argument("--e2e", action="store_true", help="Playwright E2E gate after build")
    sp.add_argument("--no-e2e", action="store_true",
                    help="override the e2e gate that is otherwise FORCED before "
                         "deploying an auth/session/form app (not recommended)")
    sp.add_argument("--chaos", action="store_true", help="chaos/resilience gate after build")
    sp.add_argument("--nfr", action="store_true",
                    help="perf/NFR budget gate: measure bundle/deps/weight vs budget "
                         "(specs/<name>/nfr.yaml blocks; defaults advisory unless --strict)")
    sp.add_argument("--nfr-build", action="store_true",
                    help="NFR: also run a clean timed build to measure build_ms")
    sp.add_argument("--perf", action="store_true",
                    help="perf/load gate: boot the built app + fire concurrent load, "
                         "measure latency percentiles/throughput/error-rate vs budget "
                         "(specs/<name>/perf.yaml blocks; defaults advisory unless --strict)")
    sp.add_argument("--perf-requests", type=int, default=200,
                    help="perf gate: total requests to fire (default 200)")
    sp.add_argument("--perf-concurrency", type=int, default=10,
                    help="perf gate: max requests in flight (default 10)")
    sp.add_argument("--visual", action="store_true",
                    help="visual-parity gate (clones): score the clone's LOOK against "
                         "the reference UI captured in specs/<name>/_ui — design tokens "
                         "+ DOM skeleton (+ screenshot diff with --visual-pixel) "
                         "(specs/<name>/visual.yaml blocks; advisory unless --strict)")
    sp.add_argument("--visual-pixel", action="store_true",
                    help="visual gate: also boot the clone and screenshot-diff it "
                         "against the LIVE reference URL (needs a url reference + "
                         "playwright/chromium; skipped gracefully otherwise)")
    sp.add_argument("--product", action="store_true",
                    help="product-fit gate: an INDEPENDENT reviewer judges whether the "
                         "built app delivers the spec's product + UX/fit gaps "
                         "(advisory; blocks only with --strict)")
    sp.add_argument("--cost", action="store_true",
                    help="hard cost-cap gate: total build spend (across retries) vs "
                         "budget — distinct from --budget's soft per-run cap "
                         "(specs/<name>/cost.yaml `max_usd:` blocks; default $15 "
                         "advisory unless --strict / --cost-max)")
    sp.add_argument("--cost-max", type=float, default=None,
                    help="cost gate: cap TOTAL build spend at this USD (blocking; "
                         "overrides cost.yaml / the default ceiling)")
    sp.add_argument("--all", action="store_true", help=_ALL_GATES_HELP)
    sp.add_argument("--deploy", action="store_true", help="deploy after a green build")
    sp.add_argument("--yes", action="store_true", help="skip the deploy human gate")
    sp.add_argument("--allow-provision-failure", action="store_true",
                    help="deploy even if creating/migrating the PRODUCTION datastore "
                         "failed (ships an app whose DB may be missing)")
    sp.add_argument("--open", dest="open", action="store_true", default=True,
                    help="(DEFAULT) after a green build, start the app + open it in "
                         "your browser so you can self-verify")
    sp.add_argument("--no-open", dest="open", action="store_false",
                    help="do not auto-open the app after a green build")


def _gate_blocking(gate: str, name: str, args: argparse.Namespace) -> Optional[bool]:
    """Was this gate in BLOCKING posture for this run? True/False, or None if unknown.

    Asks each gate's OWN budget loader instead of re-deriving the "committed yaml or
    --strict" rule, so the attestation can't drift from what the gate actually did.
    Returns None rather than guessing when a loader errors — provenance must not
    claim a posture it couldn't determine."""
    strict = bool(getattr(args, "strict", False))
    try:
        if gate == "nfr":
            from area.verify.nfr import load_budget as _nfr_budget

            return _nfr_budget(name, strict=strict)[1]
        if gate == "perf":
            from area.verify.perf import load_budget as _perf_budget

            return _perf_budget(name, strict=strict)[1]
        if gate == "visual":
            from area.verify.visual import load_threshold

            return load_threshold(name, strict=strict)[1]
        if gate == "cost":
            from area.verify.cost import load_cap

            return load_cap(name, strict=strict,
                            override=getattr(args, "cost_max", None))[1]
    except Exception:  # noqa: BLE001 — posture is metadata; record "unknown", not a guess
        return None
    if gate == "product":
        return strict  # the LLM reviewer only blocks under --strict
    return True  # verify/audit/e2e/chaos: a tier-1/oracle failure always blocks


# Commands that run an agent on the host and therefore need the factory pinned.
_FACTORY_GUARDED = ("run", "clone", "intake", "iterate")


def _factory_script() -> Path:
    return Path(__file__).resolve().parent.parent / "tools" / "verify-factory-intact.sh"


def _factory_snapshot(args: argparse.Namespace) -> None:
    """Checksum AREA's OWN code before a build.

    The build agent runs unsandboxed on the host, and with the default workspace
    (REPO/workspace) it writes INSIDE this repo — so nothing stopped it from editing a
    gate's checker, a skill, or `area/` mid-run. The lock lives in the OS temp dir, not
    the workspace, because the workspace is exactly what the agent can write.

    Best-effort: a missing script must not block a build. But the absence is recorded
    (`_factory_lock = None` → `factoryIntact: null`) so the attestation never implies a
    check that did not run."""
    args._factory_lock = None
    script = _factory_script()
    if not script.exists():
        return
    lock = Path(tempfile.gettempdir()) / f"area-factory-{os.getpid()}.lock"
    try:
        r = subprocess.run(["bash", str(script), "snapshot", str(lock)],
                           capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:  # noqa: BLE001
        print(f"[area] factory snapshot skipped (warn): {e}")
        return
    if r.returncode == 0:
        args._factory_lock = str(lock)
    else:
        print(f"[area] factory snapshot skipped (warn): {r.stderr.strip()}")


def _factory_verify(args: argparse.Namespace) -> Optional[bool]:
    """True = intact · False = CHANGED during the run · None = not checked."""
    lock = getattr(args, "_factory_lock", None)
    if not lock:
        return None
    try:
        r = subprocess.run(["bash", str(_factory_script()), "verify", str(lock)],
                           capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:  # noqa: BLE001
        print(f"[area] factory verify skipped (warn): {e}")
        return None
    finally:
        try:
            Path(lock).unlink(missing_ok=True)
        except OSError:
            pass
    out = (r.stdout.strip() or "") + ("\n" + r.stderr.strip() if r.stderr.strip() else "")
    print(out.strip())
    return True if r.returncode == 0 else (False if r.returncode == 1 else None)


def _builder_id(args: argparse.Namespace) -> str:
    """What ACTUALLY built this. Used to be a hardcoded "area/openhands-acp", which
    was simply false for `--backend llm`."""
    return f"area/{getattr(args, 'backend', None) or 'acp'}"


def _profile_digests() -> dict[str, str]:
    """{kind: digest} for every agent profile — "which policy applied" in the
    reference's sense, and the key a later `area evals` comparison hangs on."""
    try:
        from area.profile import all_profiles

        return {k: p.digest for k, p in all_profiles().items()}
    except Exception:  # noqa: BLE001
        return {}


def _run_policy(args: argparse.Namespace) -> dict[str, Any]:
    """The run's own configuration, for the attestation. Without this a past build
    can't be reconstructed: the model, strictness and caps that shaped it are gone."""
    return {
        "backend": getattr(args, "backend", None) or "acp",
        "model": getattr(args, "model", None),
        "strict": bool(getattr(args, "strict", False)),
        "tdd": bool(getattr(args, "tdd", False)),
        "auditLevel": getattr(args, "audit_level", None),
        "blockInjection": not bool(getattr(args, "no_block_injection", False)),
        "budgetUsd": getattr(args, "budget", None),
        "agentIters": getattr(args, "agent_iters", None),
        "specIters": getattr(args, "spec_iters", None),
        "buildIters": getattr(args, "build_iters", None),
        "profiles": _profile_digests(),
    }


def _finish(res: "PipelineResult", args: argparse.Namespace) -> int:
    if getattr(res, "clarify_needed", False):
        print(f"\n[area] ⏸ CLARIFICATION NEEDED — {res.name} (spec: {res.spec_dir}); "
              "not built. Confirm/override the assumptions above, then re-run "
              "(update the requirement or pass --expect).")
        return 2
    status = "✅ GREEN" if res.passed else "❌ NOT green"
    print(f"\n[area] {status} — {res.name}")
    print(f"[area] spec: {res.spec_dir}\n[area] app : {res.app_dir}")

    from area import evidence

    def _ev(event: str, data: dict[str, Any] | None = None) -> None:
        evidence.emit(res.name, event, data)

    if not res.passed:
        _ev("build.not_green")
        return 1
    _ev("build.green", {"target": getattr(args, "target", None)})

    all_ = getattr(args, "all", False)
    gates = [g for g in _GATE_ORDER if all_ or getattr(args, g, False)]
    # --tdd already builds against the locked holdout suite, so the post-build
    # 'verify' gate is redundant (it would re-author a fresh suite). Skip it.
    if getattr(args, "tdd", False) and "verify" in gates:
        gates.remove("verify")
        print("[area] (--tdd) holdout already enforced as the build oracle — "
              "skipping redundant 'verify' gate")

    # logic-green ≠ live-works: for an auth/session/form app the e2e gate caught a
    # live signup bug a passing holdout missed. Enforce it BEFORE a deploy of such
    # an app (where it actually bit); recommend it otherwise. --no-e2e overrides.
    if (_looks_auth(res.spec_dir) and "e2e" not in gates
            and not getattr(args, "no_e2e", False)):
        if args.deploy:
            gates.append("e2e")
            print("[area] 🔒 auth/session/form + deploy → e2e gate is MANDATORY "
                  "before deploy (added); pass --no-e2e to override.")
        else:
            print("[area] ⚠ auth/session/form detected — the e2e gate is strongly "
                  "recommended (logic-green ≠ live-works). Add --e2e (it is forced "
                  "before a --deploy).")

    # Apply the deterministic vinext fixes BEFORE the gates, so what the gates judge
    # — and what provenance then attests — is the app as it will actually deploy.
    # These used to run only at deploy time, i.e. AFTER the attestation, so the shipped
    # bytes differed from the gated ones. Running them here also clears the braces CVE
    # chain before `audit` sees it, which is the recurring vinext failure anyway.
    # Idempotent and a no-op on a non-Cloudflare app.
    if (getattr(args, "target", None) or "") == "cloudflare":
        try:
            from area.build.cf_scaffold import harden_cf_app

            harden_cf_app(res.app_dir)
        except Exception as e:  # noqa: BLE001 — a safety net must not break a build
            print(f"[area] cf-fix (pre-gate) skipped (warn): {e}")

    # A clone has a REFERENCE, so "does it look like the original?" has a ground truth
    # — and leaving that unmeasured is what made a clone's UI "always missing". Gates
    # are opt-in, so without this the visual gate simply never ran: AREA captured the
    # reference UI, vendored it, built a gate to score it, and then by default never
    # scored anything. Forced here (same shape as the e2e rule above), still ADVISORY
    # unless specs/<name>/visual.yaml commits a floor.
    if "visual" not in gates:
        try:
            from area.verify.visual import has_reference_ui

            if has_reference_ui(res.name):
                gates.append("visual")
                print("[area] 🎨 reference UI captured → visual-parity gate added "
                      "(advisory; commit specs/<name>/visual.yaml to enforce a floor)")
        except Exception as e:  # noqa: BLE001 — never block a build on gate selection
            print(f"[area] visual gate auto-select skipped (warn): {e}")

    for g in gates:
        print(f"\n[area] === gate: {g} ===")
        ok = _run_gate(g, res.name, args)
        _ev("gate", {"gate": g, "ok": bool(ok)})
        if not ok:
            print(f"[area] ❌ gate '{g}' failed — skipping deploy")
            return 1

    # The factory itself is in the TRUSTED row of the threat model: it "changes only
    # through review, never during a run". Check that before attesting anything — a
    # gate that graded with modified code proves nothing.
    factory_intact = _factory_verify(args)
    if factory_intact is False:
        print("[area] ❌ refusing to attest or deploy — AREA's own code changed while "
              "this build was running. Revert it and rebuild.")
        _ev("factory.tampered")
        return 1

    # SLSA-style provenance: attest what was built, which gates ACTUALLY enforced it
    # (vs merely ran advisory, vs never ran), and the policy it ran under — so deploy
    # can verify the artifact, and a human can reconstruct the build months later.
    try:
        from area.provenance import write_provenance

        gate_results: dict[str, Any] = {
            g: {"ran": True, "blocking": _gate_blocking(g, res.name, args),
                "blocked": False}  # a blocking breach returned above, so: not blocked
            for g in gates
        }
        write_provenance(res.app_dir, name=res.name,
                         target=getattr(args, "target", None) or "?",
                         gates=gate_results,
                         gates_not_run=[g for g in _GATE_ORDER if g not in gates],
                         builder=_builder_id(args),
                         policy={**_run_policy(args),
                                 "factoryIntact": factory_intact},
                         spec_dir=res.spec_dir)
        enforced = sum(1 for v in gate_results.values() if v["blocking"] is True)
        print(f"[area] provenance recorded ({enforced} enforced / {len(gates)} ran "
              f"/ {len(_GATE_ORDER) - len(gates)} not run) → .area/provenance.json")
        _ev("provenance.recorded", {"enforced": enforced, "ran": len(gates)})
    except Exception as e:  # noqa: BLE001
        print(f"[area] provenance write skipped (warn): {e}")

    # reality loop (#4): show the assumptions this build chose + how to preview +
    # the one command to refine, so the human closes the intent loop now, not later.
    try:
        from area.reality import build_reality_report

        print(build_reality_report(res.name, res.spec_dir, res.app_dir))
    except Exception as e:  # noqa: BLE001
        print(f"[area] reality report skipped (warn): {e}")

    # auto-open the built app so the user can self-verify (show→react→refine). For a
    # deploy run the deployed URL is the preview, so only open locally when not deploying.
    if getattr(args, "open", True) and not args.deploy:
        try:
            from area.preview import open_preview

            open_preview(res.app_dir, want_open=True)
        except Exception as e:  # noqa: BLE001
            print(f"[area] preview skipped (warn): {e}")

    if args.deploy:
        from area.deploy import deploy_with_gate

        ok, url = deploy_with_gate(
            res.app_dir, confirm=_confirm_fn(args.yes),
            allow_provision_failure=bool(
                getattr(args, "allow_provision_failure", False)),
        )
        _ev("deploy.done" if ok else "deploy.failed",
            {"url": url} if isinstance(url, str) else None)
        return 0 if ok else 1
    return 0


def _run_gate(gate: str, name: str, args: argparse.Namespace) -> bool:
    from area.verify import (chaos_verify, cost_verify, e2e_verify, holdout_verify,
                             nfr_verify, perf_verify, product_verify, static_audit,
                             visual_verify)

    kw = dict(backend=args.backend, model=args.model)
    strict = getattr(args, "strict", False)
    # Dispatch table keyed by gate name — kept in lockstep with _GATE_ORDER by
    # test_gate_registry (every ordered gate must have a runner here).
    runners: dict[str, Callable[[], bool]] = {
        "verify": lambda: holdout_verify(name, **kw),
        "audit": lambda: static_audit(
            name, fix=True, audit_level=getattr(args, "audit_level", "high"),
            strict=strict,
            block_injection=not getattr(args, "no_block_injection", False), **kw),
        "e2e": lambda: e2e_verify(name, **kw),
        "chaos": lambda: chaos_verify(name, **kw),
        "nfr": lambda: nfr_verify(name, strict=strict,
                                  run_build=getattr(args, "nfr_build", False), **kw),
        "perf": lambda: perf_verify(name, strict=strict,
                                    total=getattr(args, "perf_requests", 200),
                                    concurrency=getattr(args, "perf_concurrency", 10), **kw),
        "visual": lambda: visual_verify(
            name, strict=strict, pixel=getattr(args, "visual_pixel", False), **kw),
        "product": lambda: product_verify(name, strict=strict, **kw),
        "cost": lambda: cost_verify(name, strict=strict,
                                    override=getattr(args, "cost_max", None),
                                    since=getattr(args, "_build_start", None), **kw),
    }
    runner = runners.get(gate)
    return runner() if runner else True


def _build_parser() -> argparse.ArgumentParser:
    """Build the full `area` CLI parser (all subcommands + their flags)."""
    p = argparse.ArgumentParser(prog="area", description="AREA — internal AI software factory")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="Flow A: requirement -> spec -> app")
    r.add_argument("requirement", help="natural-language requirement, in quotes")
    _add_common(r)

    c = sub.add_parser("clone", help="Flow B: reverse-engineer a sample app -> spec -> app")
    c.add_argument("source", help="git URL | local path | http(s) URL of the sample app")
    c.add_argument("--kind", default="auto", choices=["auto", "repo", "path", "url"])
    c.add_argument("--rea", action="store_true",
                   help="Tier 2: use REA MCP for deep RE (authorized targets only)")
    _add_common(c)

    ig = sub.add_parser(
        "intake",
        help="Hybrid: ingest AI-DLC Inception artifacts -> spec -> app",
    )
    ig.add_argument("artifacts", help="path to AI-DLC artifact file or directory")
    _add_common(ig)

    ic = sub.add_parser(
        "inception",
        help="AI-DLC front-end: governed bolts (intent→stories→UoW→Testing Posture) "
             "→ contract-compliant Inception artifacts (then `area intake`)",
    )
    ic.add_argument("requirement", help="natural-language requirement, in quotes")
    ic.add_argument("--name", default=None, help="product name (prompted if omitted)")
    ic.add_argument("--backend", default="acp", choices=["acp", "llm"])
    ic.add_argument("--model", default=None)
    ic.add_argument("--yes", action="store_true",
                    help="non-interactive: auto-accept each bolt (drops the human gate)")
    ic.add_argument("--target", default="cloudflare", choices=["cloudflare", "vercel", "plain"],
                    help="build target used in the printed `area intake` handoff")

    it = sub.add_parser(
        "iterate",
        help="Iterate an existing app: fold a change request into its spec, "
             "re-lock the oracle (TDD), and rebuild (the 'command box')",
    )
    it.add_argument("name", help="existing app name")
    it.add_argument("request", help="natural-language change request, in quotes")
    it.add_argument("--target", default=None, choices=["cloudflare", "vercel", "plain"],
                    help="build target (default: auto-detect from the existing app)")
    it.add_argument("--no-tdd", action="store_true",
                    help="do NOT re-lock an independent holdout before building "
                         "(NOT recommended — drops the oracle guarantee)")
    it.add_argument("--backend", default="acp", choices=["acp", "llm"])
    it.add_argument("--model", default=None)
    it.add_argument("--spec-iters", type=int, default=3)
    it.add_argument("--build-iters", type=int, default=3)
    it.add_argument("--budget", type=float, default=None,
                    help="max USD spend per agent run (cost cap)")
    it.add_argument("--agent-iters", type=int, default=None)
    it.add_argument("--design", dest="design", action="store_const", const=True, default=None,
                    help="force the architect stage (default: AUTO for a non-trivial app)")
    it.add_argument("--no-design", dest="design", action="store_const", const=False,
                    help="skip the architect stage even for a non-trivial app")
    it.add_argument("--expect", default=None,
                    help="expected results / examples (authoritative, become AC)")
    it.add_argument("--expect-file", default=None)
    it.add_argument("--clarify", dest="clarify", action="store_true", default=True,
                    help="(DEFAULT) stop at spec and surface MATERIAL ambiguities before rebuilding")
    it.add_argument("--no-clarify", dest="clarify", action="store_false",
                    help="skip the clarify gate (guess + rebuild without asking); the "
                         "independent spec reviewer still runs — --no-spec-review "
                         "skips that")
    it.add_argument("--spec-review", dest="spec_review", action="store_true", default=True,
                    help="(DEFAULT) independent reviewer flags material ambiguities the spec missed")
    it.add_argument("--no-spec-review", dest="spec_review", action="store_false",
                    help="skip the independent spec-vs-intent reviewer")
    it.add_argument("--verify", action="store_true")
    it.add_argument("--audit", action="store_true")
    it.add_argument("--e2e", action="store_true")
    it.add_argument("--no-e2e", action="store_true",
                    help="override the e2e gate forced before deploying an auth app")
    it.add_argument("--chaos", action="store_true")
    it.add_argument("--nfr", action="store_true", help="perf/NFR budget gate after rebuild")
    it.add_argument("--perf", action="store_true",
                    help="perf/load gate (boot app + fire load; advisory, --strict to enforce)")
    it.add_argument("--perf-requests", type=int, default=200)
    it.add_argument("--perf-concurrency", type=int, default=10)
    it.add_argument("--strict", action="store_true",
                    help="make advisory gate findings (audit tier-2, nfr, perf, product) BLOCK")
    it.add_argument("--no-block-injection", action="store_true",
                    help="downgrade injection-class audit findings to advisory")
    it.add_argument("--product", action="store_true",
                    help="product-fit gate (advisory; --strict to enforce)")
    it.add_argument("--cost", action="store_true",
                    help="hard cost-cap gate: total rebuild spend vs budget "
                         "(specs/<name>/cost.yaml blocks; default $15 advisory)")
    it.add_argument("--cost-max", type=float, default=None,
                    help="cost gate: cap total rebuild spend at this USD (blocking)")
    it.add_argument("--all", action="store_true", help=_ALL_GATES_HELP + " (after rebuild)")
    it.add_argument("--deploy", action="store_true")
    it.add_argument("--yes", action="store_true", help="skip the deploy human gate")
    it.add_argument("--allow-provision-failure", action="store_true",
                    help="deploy even if PRODUCTION datastore provisioning failed")
    it.add_argument("--open", dest="open", action="store_true", default=True,
                    help="(DEFAULT) open the rebuilt app in your browser to verify")
    it.add_argument("--no-open", dest="open", action="store_false",
                    help="do not auto-open after rebuild")

    d = sub.add_parser("deploy", help="Deploy a built app to your infra (human gate)")
    d.add_argument("name")
    d.add_argument("--yes", action="store_true", help="skip the human gate")
    # Tri-state on purpose: absent (None) lets AREA_REQUIRE_PROVENANCE decide. As a
    # store_true with default=False this flag swallowed the env var entirely.
    d.add_argument("--require-provenance", dest="require_provenance",
                   action="store_true", default=None,
                   help="(DEFAULT) refuse to deploy an artifact AREA's gates never "
                        "attested, or that changed after gating")
    d.add_argument("--no-require-provenance", dest="require_provenance",
                   action="store_false",
                   help="deliberately ship an unattested build (a modified-after-"
                        "gating MISMATCH still refuses)")
    d.add_argument("--allow-provision-failure", action="store_true",
                   help="deploy even if creating/migrating the PRODUCTION datastore "
                        "failed (ships an app whose DB may be missing)")

    pv = sub.add_parser("provenance",
                        help="Show or verify an app's build provenance (SLSA-style)")
    pv.add_argument("name")
    pv.add_argument("--verify", action="store_true",
                    help="re-verify the built artifact against its recorded provenance "
                         "(exit 1 on mismatch/absent)")

    ex = sub.add_parser("export",
                        help="Hand a generated app off as its OWN git repo (init + commit, optional push)")
    ex.add_argument("name")
    ex.add_argument("--out", default=None,
                    help="copy the app into <out>/<name> before git-init (default: in place)")
    ex.add_argument("--repo", default=None, help="git remote URL to set as origin")
    ex.add_argument("--create", action="store_true",
                    help="create the GitHub repo via `gh repo create` (needs gh)")
    ex.add_argument("--public", action="store_true", help="with --create, make the repo public")
    ex.add_argument("--push", action="store_true", help="push to origin after the initial commit")
    ex.add_argument("-m", "--message", default=None, help="commit message")

    rb = sub.add_parser("rollback", help="Roll a deployed app back to its previous Cloudflare version")
    rb.add_argument("name")
    rb.add_argument("--version", default=None, help="specific version id (default: previous)")
    rb.add_argument("--yes", action="store_true", help="skip the human gate")

    g = sub.add_parser("gui", help="Launch the AREA web GUI")
    g.add_argument("--host", default="127.0.0.1")
    g.add_argument("--port", type=int, default=8787)
    g.add_argument("--no-open", action="store_true", help="don't auto-open the browser")

    sub.add_parser("doctor", help="Check the local setup (Python/Node/git/Claude/deploy creds)")

    dm = sub.add_parser("demo", help="Run a committed example app locally — KEYLESS "
                                     "(no Claude, no cost); omit name to list")
    dm.add_argument("name", nargs="?", default=None, help="example name (omit to list)")
    dm.add_argument("--no-open", dest="open", action="store_false", default=True,
                    help="don't auto-open the browser")
    dm.add_argument("--no-build", dest="build", action="store_false", default=True,
                    help="skip the build step (reuse an existing .next)")

    # The coordinator + runner (multi-user SaaS data plane) live on the
    # `saas-coordinator-runner` branch. On main, AREA runs natively in Claude Code.

    h = sub.add_parser("heal", help="Fix a built app at the SPEC level from an error, then regen")
    h.add_argument("name")
    h.add_argument("--error", default=None, help="error text / stack trace")
    h.add_argument("--error-file", default=None, help="file containing the error/log")
    h.add_argument("--no-rebuild", action="store_true")
    h.add_argument("--target", default="cloudflare", choices=["cloudflare", "vercel", "plain"])
    h.add_argument("--backend", default="acp", choices=["acp", "llm"])
    h.add_argument("--model", default=None)
    h.add_argument("--spec-iters", type=int, default=3)
    h.add_argument("--build-iters", type=int, default=3)
    h.add_argument("--budget", type=float, default=None)
    h.add_argument("--agent-iters", type=int, default=None)

    vf = sub.add_parser("verify", help="Independent holdout acceptance check of a built app")
    vf.add_argument("name")
    _add_agent_opts(vf)

    ob = sub.add_parser("obs", help="Show cost/latency/outcome summary of agent runs")
    ob.add_argument("--json", action="store_true")

    ev = sub.add_parser("evals", help="Grade a change to the FACTORY: compare each "
                                      "agent profile's current version against the "
                                      "previous one (prompts/skills/knobs)")
    ev.add_argument("kind", nargs="*", help="profile kind(s); default: all")
    ev.add_argument("--check", action="store_true",
                    help="exit 1 on a regression (use before promoting a change)")
    ev.add_argument("--strict", action="store_true",
                    help="also fail when there is not enough data to judge")
    ev.add_argument("--json", action="store_true")

    tr = sub.add_parser("trace", help="Show an app's end-to-end audit trail "
                                      "(Inception → spec → gates → provenance → deploy)")
    tr.add_argument("name")
    tr.add_argument("--json", action="store_true")

    sub.add_parser("mem", help="Show the experience store (pitfalls remembered)")

    dg = sub.add_parser("design", help="Architect stage: write design.md from a spec")
    dg.add_argument("name")
    dg.add_argument("--backend", default="acp", choices=["acp", "llm"])
    dg.add_argument("--model", default=None)

    e2 = sub.add_parser("e2e", help="Playwright end-to-end UI verification of a built app")
    e2.add_argument("name")
    _add_agent_opts(e2)

    au = sub.add_parser("audit", help="Security + static gate (tsc, npm audit, secrets) — two-tier")
    au.add_argument("name")
    au.add_argument("--fix", action="store_true", help="let an agent fix issues and re-gate")
    au.add_argument("--audit-level", default="high",
                    choices=["low", "moderate", "high", "critical"],
                    help="npm-audit severity threshold for the deterministic tier-1 gate")
    au.add_argument("--strict", action="store_true",
                    help="tier-2: make advisory risky-pattern findings BLOCK")
    au.add_argument("--no-block-injection", action="store_true",
                    help="downgrade injection-class findings (XSS/eval/SQL-injection, "
                         "which BLOCK by default) to advisory")
    _add_agent_opts(au)

    ch = sub.add_parser("chaos", help="Chaos/resilience test the app and harden it")
    ch.add_argument("name")
    _add_agent_opts(ch)

    pf = sub.add_parser("perf", help="Perf/load gate: boot the built app, fire load, "
                                     "measure latency/throughput/errors vs budget")
    pf.add_argument("name")
    pf.add_argument("--requests", type=int, default=200, help="total requests to fire")
    pf.add_argument("--concurrency", type=int, default=10, help="max requests in flight")
    pf.add_argument("--path", default="/", help="URL path to load-test (default /)")
    pf.add_argument("--strict", action="store_true",
                    help="make a default-budget breach BLOCK (exit 1)")
    pf.add_argument("--backend", default="acp", choices=["acp", "llm"])
    pf.add_argument("--model", default=None)

    vi = sub.add_parser("visual", help="Visual-parity gate (clones): score the "
                                       "clone's look vs the captured reference UI")
    vi.add_argument("name")
    vi.add_argument("--pixel", dest="visual_pixel", action="store_true",
                    help="also boot the clone + screenshot-diff it against the LIVE "
                         "reference URL (needs playwright/chromium)")
    vi.add_argument("--strict", action="store_true",
                    help="make a below-threshold score BLOCK (exit 1)")
    vi.add_argument("--backend", default="acp", choices=["acp", "llm"])
    vi.add_argument("--model", default=None)

    co = sub.add_parser("cost", help="Hard cost-cap gate: total build spend vs "
                                     "budget (the most-recent build session)")
    co.add_argument("name")
    co.add_argument("--max", dest="cost_max", type=float, default=None,
                    help="cap total spend at this USD (blocking; else specs/<name>/"
                         "cost.yaml or the default $15 ceiling)")
    co.add_argument("--strict", action="store_true",
                    help="make the default ceiling BLOCK (exit 1)")
    co.add_argument("--backend", default="acp", choices=["acp", "llm"])
    co.add_argument("--model", default=None)

    cf = sub.add_parser("cf-fix", help="Deterministically fix the recurring vinext "
                                       "gotchas (pin compat date to workerd + braces/"
                                       "fflate audit overrides + vendor patched braces)")
    cf.add_argument("name")

    cc = sub.add_parser("cf-clone", help="Clone a known-good CF toolchain from a "
                                         "sibling app (vinext-cf-build §2 fallback: "
                                         "reuse a toolchain that already builds green)")
    cc.add_argument("name", help="the new/target app")
    cc.add_argument("--from", dest="sibling", required=True,
                    help="sibling app name whose toolchain (lockfile + node_modules "
                         "+ configs) is reused")

    rs = sub.add_parser("research", help="`area adapt` P1: survey comparable projects "
                                         "for a reference + requirement → a research brief")
    rs.add_argument("reference", help="reference app: git URL / repo / live URL / path")
    rs.add_argument("--requirement", default="", help="what the adapted app must do")
    rs.add_argument("--count", type=int, default=100, help="candidate repos to survey")
    rs.add_argument("--top", type=int, default=5, help="top repos to analyse")
    rs.add_argument("--budget", type=float, default=None, help="max USD spend")
    rs.add_argument("--backend", default="acp", choices=["acp", "llm"])
    rs.add_argument("--model", default=None)
    rs.add_argument("--json", action="store_true", help="print the brief as JSON")

    ad = sub.add_parser("adapt", help="Research-augmented clone & adapt: research "
                                      "comparable projects + a reference → a "
                                      "requirement-anchored spec (one-shot clarify) "
                                      "→ build handoff")
    ad.add_argument("reference", help="reference app: git URL / repo / live URL / path")
    ad.add_argument("requirement", help="what the adapted app must do (authoritative)")
    ad.add_argument("--name", default=None, help="product name (slug from reference if omitted)")
    ad.add_argument("--count", type=int, default=100, help="candidate repos to survey")
    ad.add_argument("--top", type=int, default=5, help="top repos to analyse")
    ad.add_argument("--budget", type=float, default=None)
    ad.add_argument("--backend", default="acp", choices=["acp", "llm"])
    ad.add_argument("--model", default=None)
    ad.add_argument("--no-clarify", dest="clarify", action="store_false", default=True,
                    help="skip the one-shot clarify confirm (accept the filled spec)")
    ad.add_argument("--yes", action="store_true", help="auto-confirm the one-shot clarify")
    ad.add_argument("--seed", action="store_true",
                    help="opt-in: seed data from the reference (needs --seed-attest)")
    ad.add_argument("--seed-attest", action="store_true",
                    help="attest you have the right to copy the reference's data")

    mo = sub.add_parser("monitor", help="Probe a deployed app's health/latency")
    mo.add_argument("target", help="app name or https URL")
    mo.add_argument("--checks", type=int, default=5)
    mo.add_argument("--interval", type=float, default=5.0)
    mo.add_argument("--health", default="/", help="path to probe (e.g. /health)")
    mo.add_argument("--json", action="store_true")

    st = sub.add_parser("status", help="Monitoring summary of a deployed app")
    st.add_argument("name")
    st.add_argument("--json", action="store_true")

    wa = sub.add_parser("watch", help="Self-heal loop: probe->heal->rebuild->gate->redeploy")
    wa.add_argument("name")
    wa.add_argument("--checks", type=int, default=3)
    wa.add_argument("--interval", type=float, default=5.0)
    wa.add_argument("--max-heals", type=int, default=1)
    wa.add_argument("--yes", action="store_true", help="skip the redeploy human gate")
    wa.add_argument("--backend", default="acp", choices=["acp", "llm"])
    wa.add_argument("--model", default=None)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    # Stamp the invocation start so the post-build `cost` gate can sum only THIS
    # build's agent runs (obs.runs.jsonl is global + per-run; see area/verify/cost).
    args._build_start = time.time()
    # Pin AREA's own code for the commands that let an agent loose on this host, so
    # `_finish` can prove the factory did not change while it was running.
    if getattr(args, "cmd", None) in _FACTORY_GUARDED:
        _factory_snapshot(args)

    # P2 cost/budget cap -> env read by area/engine at call time
    if getattr(args, "budget", None) is not None:
        os.environ["AREA_MAX_BUDGET"] = str(args.budget)
    if getattr(args, "agent_iters", None) is not None:
        os.environ["AREA_AGENT_ITERS"] = str(args.agent_iters)

    expected = getattr(args, "expect", None)
    if getattr(args, "expect_file", None):
        try:
            expected = Path(args.expect_file).read_text()
        except OSError as e:
            print(f"[area] could not read --expect-file: {e}")
            return 1

    return _dispatch(args, expected)


# --- subcommand handlers (one per command). `expected` is used only by the build
# flows (run/clone/intake/iterate); the others accept it for a uniform table. ---

def _cmd_run(args: argparse.Namespace, expected: str | None) -> int:
    from area import trace
    from area.pipeline import run_pipeline

    name = _check_collision(_resolve_name(args.name, hint=args.requirement, fallback="app"))
    trace.start_pipeline(name, "run",
                         inputs={"requirement": args.requirement[:500], "tdd": args.tdd})
    res = run_pipeline(
        args.requirement, name=name, target=args.target,
        backend=args.backend, model=args.model,
        spec_iters=args.spec_iters, build_iters=args.build_iters,
        design=args.design, tdd=args.tdd, expected=expected, clarify=args.clarify, spec_review=args.spec_review,
    )
    rc = _finish(res, args)
    trace.end_pipeline(passed=(rc == 0), output={"name": res.name, "app": str(res.app_dir)})
    return rc


def _cmd_clone(args: argparse.Namespace, expected: str | None) -> int:
    from area import trace
    from area.pipeline import clone_pipeline

    name = _check_collision(_resolve_name(args.name, hint=args.source, fallback="clone"))
    trace.start_pipeline(name, "clone",
                         inputs={"source": args.source, "tdd": args.tdd})
    res = clone_pipeline(
        args.source, name=name, kind=args.kind,
        use_rea=args.rea, target=args.target,
        backend=args.backend, model=args.model,
        spec_iters=args.spec_iters, build_iters=args.build_iters,
        design=args.design, tdd=args.tdd, expected=expected, clarify=args.clarify, spec_review=args.spec_review,
    )
    rc = _finish(res, args)
    trace.end_pipeline(passed=(rc == 0), output={"name": res.name, "app": str(res.app_dir)})
    return rc


def _cmd_iterate(args: argparse.Namespace, expected: str | None) -> int:
    from area import trace
    from area.pipeline import iterate_pipeline

    tdd = not args.no_tdd
    args.tdd = tdd  # so _finish's redundant-verify-skip logic sees it
    trace.start_pipeline(args.name, "iterate",
                         inputs={"request": args.request[:500], "tdd": tdd})
    res = iterate_pipeline(
        args.name, args.request, target=args.target,
        backend=args.backend, model=args.model,
        spec_iters=args.spec_iters, build_iters=args.build_iters,
        design=args.design, tdd=tdd, expected=expected, clarify=args.clarify, spec_review=args.spec_review,
    )
    rc = _finish(res, args)
    trace.end_pipeline(passed=(rc == 0), output={"name": res.name, "app": str(res.app_dir)})
    return rc


def _cmd_inception(args: argparse.Namespace, expected: str | None) -> int:
    from area.inception import run_inception
    from area.pipeline import WORKSPACE

    name = _check_collision(_resolve_name(args.name, hint=args.requirement, fallback="inception"))
    out = WORKSPACE / "specs" / name / "inception"
    res = run_inception(
        args.requirement, out, approve_fn=_inception_approver(args.yes),
        backend=args.backend, model=args.model,
    )
    print(f"\n[area] ✅ Inception artifacts → {res['out']}")
    for f in res["files"]:
        print(f"  · {Path(f).name}")
    if res.get("unapproved"):
        print(f"[area] ⚠ UNAPPROVED bolts (regenerate cap hit): "
              f"{', '.join(res['unapproved'])} — review these before building.")
    if res["warnings"]:
        print("[area] ⚠ contract warnings (advisory — the Testing Posture is the oracle):")
        for w in res["warnings"]:
            print(f"    - {w}")
    print(f"[area] evidence trace: {res['trace_id']} (aidlc_trace.jsonl)")
    print(f"\n[area] → build it:  area intake {out} --name {name} --tdd --target {args.target}")
    return 0


def _cmd_intake(args: argparse.Namespace, expected: str | None) -> int:
    from area import trace
    from area.pipeline import intake_pipeline

    name = _check_collision(_resolve_name(args.name, hint=args.artifacts, fallback="intake"))
    trace.start_pipeline(name, "intake",
                         inputs={"artifacts": args.artifacts, "tdd": args.tdd})
    res = intake_pipeline(
        args.artifacts, name=name, target=args.target,
        backend=args.backend, model=args.model,
        spec_iters=args.spec_iters, build_iters=args.build_iters,
        design=args.design, tdd=args.tdd, expected=expected, clarify=args.clarify, spec_review=args.spec_review,
    )
    rc = _finish(res, args)
    trace.end_pipeline(passed=(rc == 0), output={"name": res.name, "app": str(res.app_dir)})
    return rc


def _cmd_deploy(args: argparse.Namespace, expected: str | None) -> int:
    from area.deploy import deploy_with_gate
    from area.pipeline import WORKSPACE

    app_dir = WORKSPACE / "apps" / safe_name(args.name)
    if not app_dir.exists():
        print(f"[area] no app at {app_dir}")
        return 1
    ok, _ = deploy_with_gate(
        app_dir, confirm=_confirm_fn(args.yes),
        require_provenance=getattr(args, "require_provenance", None),
        allow_provision_failure=bool(getattr(args, "allow_provision_failure", False)),
    )
    return 0 if ok else 1


def _cmd_export(args: argparse.Namespace, expected: str | None) -> int:
    from area.export import export_app

    try:
        ok, log = export_app(
            args.name, out=args.out, repo=args.repo, push=args.push,
            create=args.create, message=args.message,
            visibility="public" if args.public else "private",
        )
    except RuntimeError as e:
        print(f"[area] export: ❌ {e}")
        return 1
    print(log)
    print(f"[area] export: {'✅ done' if ok else '❌ failed'} — {args.name}")
    return 0 if ok else 1


def _cmd_provenance(args: argparse.Namespace, expected: str | None) -> int:
    from area.pipeline import WORKSPACE
    from area.provenance import read_provenance, verify_provenance

    app_dir = WORKSPACE / "apps" / safe_name(args.name)
    if not app_dir.exists():
        print(f"[area] no app at {app_dir}")
        return 1
    if args.verify:
        status, detail = verify_provenance(app_dir)
        icon = {"ok": "✅", "mismatch": "❌", "absent": "⚠"}.get(status, "?")
        print(f"[area] provenance {status} {icon} — {detail}")
        return 0 if status == "ok" else 1
    prov = read_provenance(app_dir)
    if not prov:
        print(f"[area] no provenance recorded for {args.name} "
              "(build through AREA's gates to create it)")
        return 1
    import json as _json

    print(_json.dumps(prov, indent=2))
    return 0


def _cmd_rollback(args: argparse.Namespace, expected: str | None) -> int:
    from area.deploy import rollback
    from area.pipeline import WORKSPACE

    app_dir = WORKSPACE / "apps" / safe_name(args.name)
    if not app_dir.exists():
        print(f"[area] no app at {app_dir}")
        return 1
    if not args.yes:
        try:
            ans = input(
                f"Roll {args.name} back to previous Cloudflare version? [y/N] "
            ).strip().lower()
        except EOFError:
            ans = "n"
        if ans != "y":
            print("[area] rollback cancelled")
            return 1
    ok, out = rollback(app_dir, version=args.version)
    print(out[-1000:])
    print(f"[area] rollback: {'✅ done' if ok else '❌ failed'} — {args.name}")
    return 0 if ok else 1


def _cmd_demo(args: argparse.Namespace, expected: str | None) -> int:
    from area.demo import list_examples, run_demo

    if not args.name:
        ex = list_examples()
        print("[area] example apps (keyless — no Claude/cost):",
              ", ".join(ex) or "(none committed)")
        print("  run one:  area demo <name>")
        return 0
    return run_demo(args.name, open_browser=args.open, build=args.build)


def _cmd_doctor(args: argparse.Namespace, expected: str | None) -> int:
    from area.doctor import report

    icon = {"ok": "✅", "warn": "⚠️", "fail": "❌"}
    rows = report()
    print("[area] doctor — kiểm tra môi trường local (local-first):\n")
    for name, status, detail, fix in rows:
        print(f"  {icon.get(status, '?')} {name}" + (f" — {detail}" if detail else ""))
        if fix:
            print(f"       ↳ {fix}")
    fails = [r for r in rows if r[1] == "fail"]
    print()
    if fails:
        print(f"[area] {len(fails)} thứ BẮT BUỘC còn thiếu — cài xong chạy lại `area doctor`.")
        return 1
    print("[area] ✅ Sẵn sàng. Chạy:  area gui")
    return 0


def _cmd_gui(args: argparse.Namespace, expected: str | None) -> int:
    import uvicorn

    from area.web.auth import auth_disabled, get_token, is_auto_token
    from area.web.server import app as webapp

    base = f"http://{args.host}:{args.port}"
    if auth_disabled():
        print(f"[area] GUI → {base}   ⚠ auth DISABLED (AREA_GUI_NO_AUTH)", flush=True)
    else:
        print(f"[area] GUI → {base}/?token={get_token()}", flush=True)
        if is_auto_token():
            print("[area] (auto-generated token — pin one with AREA_GUI_TOKEN. "
                  "Keep this URL private: it grants full control.)", flush=True)
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print(f"[area] ⚠ host {args.host} exposes the dashboard beyond localhost "
              "— keep the token secret.", flush=True)
    if not args.no_open:
        import threading
        import webbrowser

        open_host = "127.0.0.1" if args.host in ("0.0.0.0", "::", "") else args.host
        url = f"http://{open_host}:{args.port}/"
        if not auth_disabled():
            url += f"?token={get_token()}"

        def _open() -> None:
            import time

            time.sleep(1.2)  # let uvicorn bind first
            try:
                webbrowser.open(url)
            except Exception:  # noqa: BLE001
                pass

        threading.Thread(target=_open, daemon=True).start()
    uvicorn.run(webapp, host=args.host, port=args.port, log_level="warning")
    return 0


def _cmd_heal(args: argparse.Namespace, expected: str | None) -> int:
    from area.heal import heal

    err = args.error
    if args.error_file:
        err = Path(args.error_file).read_text()
    if not err:
        print("[area] provide --error or --error-file")
        return 1
    res = heal(
        args.name, err, target=args.target, backend=args.backend,
        model=args.model, spec_iters=args.spec_iters,
        rebuild=not args.no_rebuild, build_iters=args.build_iters,
    )
    print(
        f"\n[area] heal: spec_changed={res.spec_changed} "
        f"rebuilt={res.rebuilt} build={res.build_passed}"
    )
    return 0 if (res.build_passed is None or res.build_passed) else 1


def _cmd_verify(args: argparse.Namespace, expected: str | None) -> int:
    from area.verify import holdout_verify

    ok = holdout_verify(
        args.name, backend=args.backend, model=args.model, max_iters=args.max_iters
    )
    print(f"\n[area] holdout verify: {'✅ PASS' if ok else '❌ FAIL'} — {args.name}")
    return 0 if ok else 1


def _cmd_e2e(args: argparse.Namespace, expected: str | None) -> int:
    from area.verify import e2e_verify

    ok = e2e_verify(
        args.name, backend=args.backend, model=args.model, max_iters=args.max_iters
    )
    print(f"\n[area] e2e: {'✅ PASS' if ok else '❌ FAIL'} — {args.name}")
    return 0 if ok else 1


def _cmd_evals(args: argparse.Namespace, expected: str | None) -> int:
    """Grade a change to the FACTORY. Not an app gate: `_GATE_ORDER` decides whether
    an APP may ship, while this decides whether a change to AREA's own prompts,
    skills or knobs may be promoted — so it is a separate command (and part of
    `make check`), never a member of the app gate set."""
    import json as _json

    from area.evals import check, report_text

    ok, results = check(args.kind or None, strict=args.strict)
    if args.json:
        print(_json.dumps(results, indent=2))
    else:
        from area.profile import all_profiles

        profs = all_profiles()
        print(f"[area] evals — {len(profs)} agent profile(s); grading the CURRENT "
              "version of each against the previous one\n")
        print(report_text(results))
        unattr = sum(r.get("unattributed_runs") or 0 for r in results)
        if unattr:
            print(f"\n[area] {unattr} run(s) predate profiles and carry no digest — "
                  "they cannot be attributed, so they are excluded from every "
                  "baseline. New runs are attributed from now on.")
    if args.check:
        print(f"\n[area] evals gate: {'✅ no regression' if ok else '❌ REGRESSION'}"
              + ("" if ok else " — do not promote this change"))
        return 0 if ok else 1
    return 0


def _cmd_obs(args: argparse.Namespace, expected: str | None) -> int:
    import json as _json

    from area.obs import summary

    s = summary()
    if args.json:
        print(_json.dumps(s, indent=2))
        return 0
    print(
        f"[obs] runs={s['runs']} · total ${s['total_cost_usd']} · {s['total_time_s']}s"
        + (f" · avg ${s['avg_cost_usd']}/run" if s.get("avg_cost_usd") is not None else "")
    )
    if s.get("first_try_rate") is not None:
        print(
            f"[obs] determinism: first-try "
            f"{round(s['first_try_rate'] * 100)}% · retry "
            f"{round(s['retry_rate'] * 100)}% · avg {s['avg_iters']} attempt(s) "
            f"(over {s['convergence_runs']} convergence run(s))"
        )
    for lbl, d in sorted(s["by_label"].items()):
        det = (f" · first-try {d['first_try']}/{d['conv_n']} · avg {d['avg_iters']}it"
               if d["conv_n"] else "")
        print(
            f"  {lbl:18} n={d['n']} ok={d['ok']} "
            f"${round(d['cost'], 4)} (avg ${d['avg_cost']}) {round(d['time'], 1)}s{det}"
        )
    return 0


def _cmd_trace(args: argparse.Namespace, expected: str | None) -> int:
    import datetime

    from area.evidence import read_trail

    recs = read_trail(args.name)
    if args.json:
        import json as _json

        print(_json.dumps(recs, indent=2))
        return 0
    if not recs:
        print(f"[area] no audit trail for {args.name} "
              "(run `area inception`/`run` to create one)")
        return 1
    traces = {r.get("trace") for r in recs if r.get("trace")}
    print(f"[area] audit trail — {args.name} · {len(recs)} events · "
          f"{len(traces)} trace(s)")
    for r in recs:
        ts = datetime.datetime.fromtimestamp(r.get("ts", 0)).strftime("%H:%M:%S")
        data = r.get("data") or {}
        extra = " ".join(f"{k}={v}" for k, v in data.items()
                         if k != "requirement")[:72]
        print(f"  {ts}  {r.get('event', ''):26} {extra}  [{(r.get('trace') or '')[:14]}]")
    return 0


def _cmd_mem(args: argparse.Namespace, expected: str | None) -> int:
    from area.memory import lessons

    ls = lessons()
    print(f"[mem] {len(ls)} lesson(s)")
    for e in ls[-30:]:
        print(f"  [{','.join(e.get('tags', []))}] {e.get('symptom', '')[:110]}")
        if e.get("fix"):
            print(f"      FIX: {e['fix'][:110]}")
    return 0


def _cmd_design(args: argparse.Namespace, expected: str | None) -> int:
    from area.design import design_stage

    txt = design_stage(args.name, backend=args.backend, model=args.model)
    print(f"\n[area] design: {'✅ wrote design.md' if txt else '❌ none'} — {args.name}")
    return 0 if txt else 1


def _cmd_audit(args: argparse.Namespace, expected: str | None) -> int:
    from area.verify import static_audit

    ok = static_audit(
        args.name, fix=args.fix, backend=args.backend, model=args.model,
        max_iters=args.max_iters, audit_level=args.audit_level, strict=args.strict,
        block_injection=not getattr(args, "no_block_injection", False),
    )
    print(f"\n[area] audit: {'✅ PASS' if ok else '❌ FAIL'} — {args.name}")
    return 0 if ok else 1


def _cmd_chaos(args: argparse.Namespace, expected: str | None) -> int:
    from area.verify import chaos_verify

    ok = chaos_verify(
        args.name, backend=args.backend, model=args.model, max_iters=args.max_iters
    )
    print(f"\n[area] chaos: {'✅ PASS' if ok else '❌ FAIL'} — {args.name}")
    return 0 if ok else 1


def _cmd_perf(args: argparse.Namespace, expected: str | None) -> int:
    from area.verify import perf_verify

    ok = perf_verify(
        args.name, backend=args.backend, model=args.model, strict=args.strict,
        total=args.requests, concurrency=args.concurrency, path=args.path,
    )
    print(f"\n[area] perf: {'✅ PASS' if ok else '❌ FAIL'} — {args.name}")
    return 0 if ok else 1


def _cmd_visual(args: argparse.Namespace, expected: str | None) -> int:
    from area.verify import visual_verify

    ok = visual_verify(
        args.name, backend=args.backend, model=args.model,
        strict=getattr(args, "strict", False),
        pixel=getattr(args, "visual_pixel", False),
    )
    # "not blocking" rather than "PASS": an advisory breach also returns True, and
    # claiming PASS right under a "below threshold" line would be a lie.
    print(f"\n[area] visual gate: {'✅ not blocking' if ok else '❌ BLOCKING'} "
          f"— {args.name}")
    return 0 if ok else 1


def _cmd_cost(args: argparse.Namespace, expected: str | None) -> int:
    from area.verify import cost_verify

    # standalone: no build just ran, so sum the most-recent build SESSION
    # (since=None → the time-gap heuristic in area/verify/cost).
    ok = cost_verify(
        args.name, backend=args.backend, model=args.model,
        strict=getattr(args, "strict", False),
        override=getattr(args, "cost_max", None), since=None,
    )
    return 0 if ok else 1


def _cmd_cf_fix(args: argparse.Namespace, expected: str | None) -> int:
    from area.build.cf_scaffold import harden_cf_app
    from area.pipeline import WORKSPACE

    app = WORKSPACE / "apps" / safe_name(args.name)
    if not app.is_dir():
        print(f"[area] no app at {app}")
        return 1
    harden_cf_app(app)
    return 0


def _cmd_cf_clone(args: argparse.Namespace, expected: str | None) -> int:
    from area.build.cf_scaffold import (clone_sibling_toolchain, harden_cf_app,
                                        restore_vendored_braces)
    from area.pipeline import WORKSPACE

    sib = WORKSPACE / "apps" / safe_name(args.sibling)
    if not sib.is_dir():
        print(f"[area] no sibling app at {sib}")
        return 1
    app = WORKSPACE / "apps" / safe_name(args.name)
    copied = clone_sibling_toolchain(app, sib)
    harden_cf_app(app)
    restore_vendored_braces(app)
    print(f"[area] cloned {len(copied)} toolchain item(s) from {args.sibling} → "
          f"{args.name}; run `npm run build:cf` to verify")
    return 0


def _cmd_research(args: argparse.Namespace, expected: str | None) -> int:
    import json as _json

    from area.research import research, validate_brief

    brief = research(args.reference, args.requirement, backend=args.backend,
                     model=args.model, budget=args.budget, count=args.count,
                     top=args.top)
    if getattr(args, "json", False):
        print(_json.dumps(brief.to_dict(), indent=2))
    else:
        print(f"[research] {len(brief.top)} repo(s) for {args.reference!r} "
              f"(from {brief.candidates_considered} considered)")
        for r in brief.top:
            print(f"  • {r.repo} ({r.score:.2f}) — data: {r.data_source} / "
                  f"{r.data_integration} / {r.data_storage}")
    for issue in validate_brief(brief):
        print(f"  ⚠ {issue}")
    return 0


def _cmd_adapt(args: argparse.Namespace, expected: str | None) -> int:
    from area.adapt import AdaptResult, adapt_pipeline
    from area.seed import SeedPolicy

    name = _resolve_name(args.name, hint=args.reference, fallback="adapt")
    seed_policy = SeedPolicy(attested=args.seed_attest) if args.seed else None

    def _confirm(_res: "AdaptResult") -> bool:
        return bool(getattr(args, "yes", False))  # one-shot: --yes accepts the filled spec

    res = adapt_pipeline(
        args.reference, args.requirement, name=name, summary=args.requirement[:200],
        backend=args.backend, model=args.model, budget=args.budget,
        count=args.count, top=args.top, clarify=args.clarify, confirm=_confirm,
        seed_policy=seed_policy)

    print(f"\n[adapt] {len(res.spec.features)} feature(s) · "
          f"data: {res.data_plan.storage} / {res.data_plan.integration}")
    if res.clarify_needed:
        print("[adapt] ⏸ CLARIFY — the requirement was silent on these; review the "
              "filled spec, then re-run with --yes (or --no-clarify) to accept:")
        for it in res.clarify_items:
            if it["auto_filled"]:
                print(f"    • {it['id']} (from {it['source']})")
        return 2
    print(f"[adapt] spec written → {res.spec_dir}")
    print(f"[adapt] build it: area intake {res.spec_dir} --name {name} --tdd")
    if res.seed is not None:
        s = res.seed
        print(f"[adapt] seed: {'OK ' + str(s.seeded) + ' record(s)' if s.ok else 'BLOCKED — ' + s.blocked_reason}")
    return 0


def _cmd_monitor(args: argparse.Namespace, expected: str | None) -> int:
    import json as _json

    from area.monitor import monitor as _mon

    m = _mon(args.target, checks=args.checks, interval=args.interval,
             health=args.health)
    if args.json:
        print(_json.dumps({k: v for k, v in m.items() if k != "results"}, indent=2))
    else:
        print(f"\n[area] monitor: {m['name']} uptime={m['uptime_pct']}% "
              f"avg={m['avg_ms']}ms ({m['ok']}/{m['checks']})")
    return 0 if m["ok"] == m["checks"] else 1


def _cmd_status(args: argparse.Namespace, expected: str | None) -> int:
    import json as _json

    from area.monitor import status as _st

    s = _st(args.name)
    if args.json:
        print(_json.dumps(s, indent=2))
    else:
        print(f"[area] status {s['name']}: url={s['url']} "
              f"uptime={s['uptime_pct']}% avg={s['avg_ms']}ms "
              f"p95={s['p95_ms']}ms samples={s['samples']}")
    return 0


def _cmd_watch(args: argparse.Namespace, expected: str | None) -> int:
    from area.monitor import watch as _watch

    ok = _watch(args.name, checks=args.checks, interval=args.interval,
                max_heals=args.max_heals, confirm=_confirm_fn(args.yes),
                backend=args.backend, model=args.model)
    print(f"\n[area] watch: {'✅ healthy/healed' if ok else '❌ needs attention'} — {args.name}")
    return 0 if ok else 1


_HANDLERS: dict[str, Callable[[argparse.Namespace, str | None], int]] = {
    "run": _cmd_run, "clone": _cmd_clone, "iterate": _cmd_iterate,
    "inception": _cmd_inception, "intake": _cmd_intake, "deploy": _cmd_deploy,
    "export": _cmd_export, "provenance": _cmd_provenance, "rollback": _cmd_rollback,
    "demo": _cmd_demo, "doctor": _cmd_doctor, "gui": _cmd_gui, "heal": _cmd_heal,
    "verify": _cmd_verify, "e2e": _cmd_e2e, "obs": _cmd_obs, "trace": _cmd_trace,
    "mem": _cmd_mem, "design": _cmd_design, "audit": _cmd_audit, "chaos": _cmd_chaos,
    "evals": _cmd_evals,
    "perf": _cmd_perf, "visual": _cmd_visual, "cost": _cmd_cost,
    "cf-fix": _cmd_cf_fix,
    "cf-clone": _cmd_cf_clone, "research": _cmd_research, "adapt": _cmd_adapt,
    "monitor": _cmd_monitor, "status": _cmd_status, "watch": _cmd_watch,
}


def _dispatch(args: argparse.Namespace, expected: str | None) -> int:
    """Run the handler for the parsed subcommand. Returns the process exit code."""
    handler = _HANDLERS.get(args.cmd)
    return handler(args, expected) if handler else 2


if __name__ == "__main__":
    raise SystemExit(main())
