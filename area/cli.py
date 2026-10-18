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
    sp.add_argument("--target", default="cloudflare", choices=["cloudflare", "plain"])
    sp.add_argument("--backend", default="acp", choices=["acp", "llm"])
    sp.add_argument("--model", default=None)
    sp.add_argument("--spec-iters", type=int, default=3)
    sp.add_argument("--build-iters", type=int, default=3)
    sp.add_argument("--budget", type=float, default=None,
                    help="max USD spend per agent run (cost cap)")
    sp.add_argument("--agent-iters", type=int, default=None,
                    help="max steps per agent run (default 80)")
    sp.add_argument("--verify", action="store_true",
                    help="independent holdout acceptance check after a green build")
    sp.add_argument("--deploy", action="store_true", help="deploy after a green build")
    sp.add_argument("--yes", action="store_true", help="skip the deploy human gate")


def _finish(res, args) -> int:
    status = "✅ GREEN" if res.passed else "❌ NOT green"
    print(f"\n[area] {status} — {res.name}")
    print(f"[area] spec: {res.spec_dir}\n[area] app : {res.app_dir}")
    if not res.passed:
        return 1
    if getattr(args, "verify", False):
        from area.verify import holdout_verify

        if not holdout_verify(res.name, backend=args.backend, model=args.model):
            print("[area] ❌ holdout verify failed — skipping deploy")
            return 1
    if args.deploy:
        from area.deploy import deploy_with_gate

        ok, _ = deploy_with_gate(res.app_dir, confirm=_confirm_fn(args.yes))
        return 0 if ok else 1
    return 0


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
    h.add_argument("--target", default="cloudflare", choices=["cloudflare", "plain"])
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

    e2 = sub.add_parser("e2e", help="Playwright end-to-end UI verification of a built app")
    e2.add_argument("name")
    e2.add_argument("--backend", default="acp", choices=["acp", "llm"])
    e2.add_argument("--model", default=None)
    e2.add_argument("--max-iters", type=int, default=3)
    e2.add_argument("--budget", type=float, default=None)
    e2.add_argument("--agent-iters", type=int, default=None)

    args = p.parse_args(argv)

    # P2 cost/budget cap -> env read by area/engine at call time
    if getattr(args, "budget", None) is not None:
        os.environ["AREA_MAX_BUDGET"] = str(args.budget)
    if getattr(args, "agent_iters", None) is not None:
        os.environ["AREA_AGENT_ITERS"] = str(args.agent_iters)

    if args.cmd == "run":
        from area.pipeline import run_pipeline

        res = run_pipeline(
            args.requirement, name=args.name or "app", target=args.target,
            backend=args.backend, model=args.model,
            spec_iters=args.spec_iters, build_iters=args.build_iters,
        )
        return _finish(res, args)

    if args.cmd == "clone":
        from area.pipeline import clone_pipeline

        res = clone_pipeline(
            args.source, name=args.name or "clone", kind=args.kind,
            use_rea=args.rea, target=args.target,
            backend=args.backend, model=args.model,
            spec_iters=args.spec_iters, build_iters=args.build_iters,
        )
        return _finish(res, args)

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

        from area.web.server import app as webapp

        print(f"[area] GUI → http://{args.host}:{args.port}")
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

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
