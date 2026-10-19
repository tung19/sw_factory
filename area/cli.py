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
    sp.add_argument("--design", action="store_true",
                    help="run the architect stage (design.md) before build")
    sp.add_argument("--tdd", action="store_true",
                    help="TDD: lock independent acceptance tests BEFORE build; "
                         "the build oracle IS that locked suite (implies verify)")
    sp.add_argument("--expect", default=None,
                    help="expected results / examples — authoritative, become "
                         "acceptance criteria (you supply part of the oracle)")
    sp.add_argument("--expect-file", default=None,
                    help="file containing expected results / examples")
    sp.add_argument("--clarify", action="store_true",
                    help="stop at spec and surface MATERIAL ambiguities (assumptions) "
                         "before building, instead of guessing silently")
    sp.add_argument("--verify", action="store_true",
                    help="independent holdout acceptance check after a green build")
    sp.add_argument("--audit", action="store_true", help="security/static gate after build")
    sp.add_argument("--e2e", action="store_true", help="Playwright E2E gate after build")
    sp.add_argument("--chaos", action="store_true", help="chaos/resilience gate after build")
    sp.add_argument("--all", action="store_true",
                    help="run all gates: verify + audit + e2e + chaos")
    sp.add_argument("--deploy", action="store_true", help="deploy after a green build")
    sp.add_argument("--yes", action="store_true", help="skip the deploy human gate")


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
        g for g in ("verify", "audit", "e2e", "chaos")
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

    if args.deploy:
        from area.deploy import deploy_with_gate

        ok, _ = deploy_with_gate(res.app_dir, confirm=_confirm_fn(args.yes))
        return 0 if ok else 1
    return 0


def _run_gate(gate: str, name: str, args) -> bool:
    from area.verify import chaos_verify, e2e_verify, holdout_verify, static_audit

    kw = dict(backend=args.backend, model=args.model)
    if gate == "verify":
        return holdout_verify(name, **kw)
    if gate == "audit":
        return static_audit(name, fix=True, **kw)
    if gate == "e2e":
        return e2e_verify(name, **kw)
    if gate == "chaos":
        return chaos_verify(name, **kw)
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
    it.add_argument("--design", action="store_true")
    it.add_argument("--expect", default=None,
                    help="expected results / examples (authoritative, become AC)")
    it.add_argument("--expect-file", default=None)
    it.add_argument("--clarify", action="store_true",
                    help="stop at spec and surface MATERIAL ambiguities before rebuilding")
    it.add_argument("--verify", action="store_true")
    it.add_argument("--audit", action="store_true")
    it.add_argument("--e2e", action="store_true")
    it.add_argument("--chaos", action="store_true")
    it.add_argument("--all", action="store_true", help="run all gates after rebuild")
    it.add_argument("--deploy", action="store_true")
    it.add_argument("--yes", action="store_true", help="skip the deploy human gate")

    d = sub.add_parser("deploy", help="Deploy a built app to Cloudflare (human gate)")
    d.add_argument("name")
    d.add_argument("--yes", action="store_true", help="skip the human gate")

    rb = sub.add_parser("rollback", help="Roll a deployed app back to its previous Cloudflare version")
    rb.add_argument("name")
    rb.add_argument("--version", default=None, help="specific version id (default: previous)")
    rb.add_argument("--yes", action="store_true", help="skip the human gate")

    g = sub.add_parser("gui", help="Launch the AREA web GUI")
    g.add_argument("--host", default="127.0.0.1")
    g.add_argument("--port", type=int, default=8787)

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

    au = sub.add_parser("audit", help="Security + static gate (tsc, npm audit, secrets)")
    au.add_argument("name")
    au.add_argument("--fix", action="store_true", help="let an agent fix issues and re-gate")
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
            design=args.design, tdd=args.tdd, expected=expected, clarify=args.clarify,
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
            design=args.design, tdd=args.tdd, expected=expected, clarify=args.clarify,
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
            design=args.design, tdd=tdd, expected=expected, clarify=args.clarify,
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
            design=args.design, tdd=args.tdd, expected=expected, clarify=args.clarify,
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
        ok, _ = deploy_with_gate(app_dir, confirm=_confirm_fn(args.yes))
        return 0 if ok else 1

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
            max_iters=args.max_iters,
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
