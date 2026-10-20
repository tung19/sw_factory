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
from pathlib import Path

from area._util import safe_name


def _confirm_fn(assume_yes: bool):
    def confirm(path: str) -> bool:
        if assume_yes:
            return True
        try:
            ans = input(f"Deploy {path} to Cloudflare PRODUCTION? [y/N] ").strip().lower()
        except EOFError:
            return False
        return ans == "y"

    return confirm


def _add_common(sp):
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
                         "asking (NOT recommended for a vague requirement)")
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
    sp.add_argument("--e2e", action="store_true", help="Playwright E2E gate after build")
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
    sp.add_argument("--product", action="store_true",
                    help="product-fit gate: an INDEPENDENT reviewer judges whether the "
                         "built app delivers the spec's product + UX/fit gaps "
                         "(advisory; blocks only with --strict)")
    sp.add_argument("--all", action="store_true",
                    help="run all gates: verify + audit + e2e + chaos + nfr + perf + product")
    sp.add_argument("--deploy", action="store_true", help="deploy after a green build")
    sp.add_argument("--yes", action="store_true", help="skip the deploy human gate")
    sp.add_argument("--open", dest="open", action="store_true", default=True,
                    help="(DEFAULT) after a green build, start the app + open it in "
                         "your browser so you can self-verify")
    sp.add_argument("--no-open", dest="open", action="store_false",
                    help="do not auto-open the app after a green build")


def _finish(res, args) -> int:
    if getattr(res, "clarify_needed", False):
        print(f"\n[area] ⏸ CLARIFICATION NEEDED — {res.name} (spec: {res.spec_dir}); "
              "not built. Confirm/override the assumptions above, then re-run "
              "(update the requirement or pass --expect).")
        return 2
    status = "✅ GREEN" if res.passed else "❌ NOT green"
    print(f"\n[area] {status} — {res.name}")
    print(f"[area] spec: {res.spec_dir}\n[area] app : {res.app_dir}")
    if not res.passed:
        return 1

    all_ = getattr(args, "all", False)
    gates = [
        g for g in ("verify", "audit", "e2e", "chaos", "nfr", "perf", "product")
        if all_ or getattr(args, g, False)
    ]
    # --tdd already builds against the locked holdout suite, so the post-build
    # 'verify' gate is redundant (it would re-author a fresh suite). Skip it.
    if getattr(args, "tdd", False) and "verify" in gates:
        gates.remove("verify")
        print("[area] (--tdd) holdout already enforced as the build oracle — "
              "skipping redundant 'verify' gate")
    for g in gates:
        print(f"\n[area] === gate: {g} ===")
        if not _run_gate(g, res.name, args):
            print(f"[area] ❌ gate '{g}' failed — skipping deploy")
            return 1

    # SLSA-style provenance: attest what was built + which gates passed, so deploy
    # can later verify the artifact wasn't modified after gating.
    try:
        from area.provenance import write_provenance

        gate_results = {g: True for g in gates}
        gate_results["holdout_tdd"] = bool(getattr(args, "tdd", False))
        write_provenance(res.app_dir, name=res.name,
                         target=getattr(args, "target", None) or "?",
                         gates=gate_results, spec_dir=res.spec_dir)
        print(f"[area] provenance recorded ({sum(gate_results.values())} checks) "
              "→ .area/provenance.json")
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

        ok, _ = deploy_with_gate(res.app_dir, confirm=_confirm_fn(args.yes))
        return 0 if ok else 1
    return 0


def _run_gate(gate: str, name: str, args) -> bool:
    from area.verify import (chaos_verify, e2e_verify, holdout_verify, nfr_verify,
                             perf_verify, product_verify, static_audit)

    kw = dict(backend=args.backend, model=args.model)
    if gate == "verify":
        return holdout_verify(name, **kw)
    if gate == "audit":
        return static_audit(name, fix=True,
                            audit_level=getattr(args, "audit_level", "high"),
                            strict=getattr(args, "strict", False), **kw)
    if gate == "e2e":
        return e2e_verify(name, **kw)
    if gate == "chaos":
        return chaos_verify(name, **kw)
    if gate == "nfr":
        return nfr_verify(name, strict=getattr(args, "strict", False),
                          run_build=getattr(args, "nfr_build", False), **kw)
    if gate == "perf":
        return perf_verify(name, strict=getattr(args, "strict", False),
                           total=getattr(args, "perf_requests", 200),
                           concurrency=getattr(args, "perf_concurrency", 10), **kw)
    if gate == "product":
        return product_verify(name, strict=getattr(args, "strict", False), **kw)
    return True


def main(argv=None) -> int:
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
                    help="skip the clarify gate (guess + rebuild without asking)")
    it.add_argument("--spec-review", dest="spec_review", action="store_true", default=True,
                    help="(DEFAULT) independent reviewer flags material ambiguities the spec missed")
    it.add_argument("--no-spec-review", dest="spec_review", action="store_false",
                    help="skip the independent spec-vs-intent reviewer")
    it.add_argument("--verify", action="store_true")
    it.add_argument("--audit", action="store_true")
    it.add_argument("--e2e", action="store_true")
    it.add_argument("--chaos", action="store_true")
    it.add_argument("--nfr", action="store_true", help="perf/NFR budget gate after rebuild")
    it.add_argument("--perf", action="store_true",
                    help="perf/load gate (boot app + fire load; advisory, --strict to enforce)")
    it.add_argument("--perf-requests", type=int, default=200)
    it.add_argument("--perf-concurrency", type=int, default=10)
    it.add_argument("--strict", action="store_true",
                    help="make advisory gate findings (audit tier-2, nfr, perf, product) BLOCK")
    it.add_argument("--product", action="store_true",
                    help="product-fit gate (advisory; --strict to enforce)")
    it.add_argument("--all", action="store_true", help="run all gates after rebuild")
    it.add_argument("--deploy", action="store_true")
    it.add_argument("--yes", action="store_true", help="skip the deploy human gate")
    it.add_argument("--open", dest="open", action="store_true", default=True,
                    help="(DEFAULT) open the rebuilt app in your browser to verify")
    it.add_argument("--no-open", dest="open", action="store_false",
                    help="do not auto-open after rebuild")

    d = sub.add_parser("deploy", help="Deploy a built app to Cloudflare (human gate)")
    d.add_argument("name")
    d.add_argument("--yes", action="store_true", help="skip the human gate")
    d.add_argument("--require-provenance", action="store_true",
                   help="refuse to deploy unless build provenance verifies "
                        "(hard block on a modified-after-gating / ungated artifact)")

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
    vf.add_argument("--backend", default="acp", choices=["acp", "llm"])
    vf.add_argument("--model", default=None)
    vf.add_argument("--max-iters", type=int, default=3)
    vf.add_argument("--budget", type=float, default=None)
    vf.add_argument("--agent-iters", type=int, default=None)

    ob = sub.add_parser("obs", help="Show cost/latency/outcome summary of agent runs")
    ob.add_argument("--json", action="store_true")

    mm = sub.add_parser("mem", help="Show the experience store (pitfalls remembered)")

    dg = sub.add_parser("design", help="Architect stage: write design.md from a spec")
    dg.add_argument("name")
    dg.add_argument("--backend", default="acp", choices=["acp", "llm"])
    dg.add_argument("--model", default=None)

    e2 = sub.add_parser("e2e", help="Playwright end-to-end UI verification of a built app")
    e2.add_argument("name")
    e2.add_argument("--backend", default="acp", choices=["acp", "llm"])
    e2.add_argument("--model", default=None)
    e2.add_argument("--max-iters", type=int, default=3)
    e2.add_argument("--budget", type=float, default=None)
    e2.add_argument("--agent-iters", type=int, default=None)

    au = sub.add_parser("audit", help="Security + static gate (tsc, npm audit, secrets) — two-tier")
    au.add_argument("name")
    au.add_argument("--fix", action="store_true", help="let an agent fix issues and re-gate")
    au.add_argument("--audit-level", default="high",
                    choices=["low", "moderate", "high", "critical"],
                    help="npm-audit severity threshold for the deterministic tier-1 gate")
    au.add_argument("--strict", action="store_true",
                    help="tier-2: make advisory risky-pattern findings BLOCK")
    au.add_argument("--backend", default="acp", choices=["acp", "llm"])
    au.add_argument("--model", default=None)
    au.add_argument("--max-iters", type=int, default=3)
    au.add_argument("--budget", type=float, default=None)
    au.add_argument("--agent-iters", type=int, default=None)

    ch = sub.add_parser("chaos", help="Chaos/resilience test the app and harden it")
    ch.add_argument("name")
    ch.add_argument("--backend", default="acp", choices=["acp", "llm"])
    ch.add_argument("--model", default=None)
    ch.add_argument("--max-iters", type=int, default=3)
    ch.add_argument("--budget", type=float, default=None)
    ch.add_argument("--agent-iters", type=int, default=None)

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

    args = p.parse_args(argv)

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

    if args.cmd == "run":
        from area import trace
        from area.pipeline import run_pipeline

        trace.start_pipeline(args.name or "app", "run",
                             inputs={"requirement": args.requirement[:500], "tdd": args.tdd})
        res = run_pipeline(
            args.requirement, name=args.name or "app", target=args.target,
            backend=args.backend, model=args.model,
            spec_iters=args.spec_iters, build_iters=args.build_iters,
            design=args.design, tdd=args.tdd, expected=expected, clarify=args.clarify, spec_review=args.spec_review,
        )
        rc = _finish(res, args)
        trace.end_pipeline(passed=(rc == 0), output={"name": res.name, "app": str(res.app_dir)})
        return rc

    if args.cmd == "clone":
        from area import trace
        from area.pipeline import clone_pipeline

        trace.start_pipeline(args.name or "clone", "clone",
                             inputs={"source": args.source, "tdd": args.tdd})
        res = clone_pipeline(
            args.source, name=args.name or "clone", kind=args.kind,
            use_rea=args.rea, target=args.target,
            backend=args.backend, model=args.model,
            spec_iters=args.spec_iters, build_iters=args.build_iters,
            design=args.design, tdd=args.tdd, expected=expected, clarify=args.clarify, spec_review=args.spec_review,
        )
        rc = _finish(res, args)
        trace.end_pipeline(passed=(rc == 0), output={"name": res.name, "app": str(res.app_dir)})
        return rc

    if args.cmd == "iterate":
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

    if args.cmd == "intake":
        from area import trace
        from area.pipeline import intake_pipeline

        trace.start_pipeline(args.name or "intake", "intake",
                             inputs={"artifacts": args.artifacts, "tdd": args.tdd})
        res = intake_pipeline(
            args.artifacts, name=args.name or "intake", target=args.target,
            backend=args.backend, model=args.model,
            spec_iters=args.spec_iters, build_iters=args.build_iters,
            design=args.design, tdd=args.tdd, expected=expected, clarify=args.clarify, spec_review=args.spec_review,
        )
        rc = _finish(res, args)
        trace.end_pipeline(passed=(rc == 0), output={"name": res.name, "app": str(res.app_dir)})
        return rc

    if args.cmd == "deploy":
        from area.deploy import deploy_with_gate
        from area.pipeline import WORKSPACE

        app_dir = WORKSPACE / "apps" / safe_name(args.name)
        if not app_dir.exists():
            print(f"[area] no app at {app_dir}")
            return 1
        ok, _ = deploy_with_gate(app_dir, confirm=_confirm_fn(args.yes),
                                 require_provenance=getattr(args, "require_provenance", False))
        return 0 if ok else 1

    if args.cmd == "export":
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

    if args.cmd == "provenance":
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

    if args.cmd == "rollback":
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

    if args.cmd == "doctor":
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

    if args.cmd == "gui":
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

            def _open():
                import time

                time.sleep(1.2)  # let uvicorn bind first
                try:
                    webbrowser.open(url)
                except Exception:  # noqa: BLE001
                    pass

            threading.Thread(target=_open, daemon=True).start()
        uvicorn.run(webapp, host=args.host, port=args.port, log_level="warning")
        return 0

    if args.cmd == "heal":
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

    if args.cmd == "verify":
        from area.verify import holdout_verify

        ok = holdout_verify(
            args.name, backend=args.backend, model=args.model, max_iters=args.max_iters
        )
        print(f"\n[area] holdout verify: {'✅ PASS' if ok else '❌ FAIL'} — {args.name}")
        return 0 if ok else 1

    if args.cmd == "e2e":
        from area.verify import e2e_verify

        ok = e2e_verify(
            args.name, backend=args.backend, model=args.model, max_iters=args.max_iters
        )
        print(f"\n[area] e2e: {'✅ PASS' if ok else '❌ FAIL'} — {args.name}")
        return 0 if ok else 1

    if args.cmd == "obs":
        import json as _json

        from area.obs import summary

        s = summary()
        if args.json:
            print(_json.dumps(s, indent=2))
            return 0
        print(
            f"[obs] runs={s['runs']} · total ${s['total_cost_usd']} · {s['total_time_s']}s"
        )
        for lbl, d in sorted(s["by_label"].items()):
            print(
                f"  {lbl:16} n={d['n']} ok={d['ok']} "
                f"${round(d['cost'], 4)} {round(d['time'], 1)}s"
            )
        return 0

    if args.cmd == "mem":
        from area.memory import lessons

        ls = lessons()
        print(f"[mem] {len(ls)} lesson(s)")
        for e in ls[-30:]:
            print(f"  [{','.join(e.get('tags', []))}] {e.get('symptom', '')[:110]}")
            if e.get("fix"):
                print(f"      FIX: {e['fix'][:110]}")
        return 0

    if args.cmd == "design":
        from area.design import design_stage

        txt = design_stage(args.name, backend=args.backend, model=args.model)
        print(f"\n[area] design: {'✅ wrote design.md' if txt else '❌ none'} — {args.name}")
        return 0 if txt else 1

    if args.cmd == "audit":
        from area.verify import static_audit

        ok = static_audit(
            args.name, fix=args.fix, backend=args.backend, model=args.model,
            max_iters=args.max_iters, audit_level=args.audit_level, strict=args.strict,
        )
        print(f"\n[area] audit: {'✅ PASS' if ok else '❌ FAIL'} — {args.name}")
        return 0 if ok else 1

    if args.cmd == "chaos":
        from area.verify import chaos_verify

        ok = chaos_verify(
            args.name, backend=args.backend, model=args.model, max_iters=args.max_iters
        )
        print(f"\n[area] chaos: {'✅ PASS' if ok else '❌ FAIL'} — {args.name}")
        return 0 if ok else 1

    if args.cmd == "perf":
        from area.verify import perf_verify

        ok = perf_verify(
            args.name, backend=args.backend, model=args.model, strict=args.strict,
            total=args.requests, concurrency=args.concurrency, path=args.path,
        )
        print(f"\n[area] perf: {'✅ PASS' if ok else '❌ FAIL'} — {args.name}")
        return 0 if ok else 1

    if args.cmd == "monitor":
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

    if args.cmd == "status":
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

    if args.cmd == "watch":
        from area.monitor import watch as _watch

        ok = _watch(args.name, checks=args.checks, interval=args.interval,
                    max_heals=args.max_heals, confirm=_confirm_fn(args.yes),
                    backend=args.backend, model=args.model)
        print(f"\n[area] watch: {'✅ healthy/healed' if ok else '❌ needs attention'} — {args.name}")
        return 0 if ok else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
