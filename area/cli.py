"""area CLI.

    area run   "<requirement>" [--name N] [--target cloudflare|plain] [--deploy]
    area clone "<git-url|path|http-url>" [--name N] [--kind auto|repo|path|url]
                                         [--target ...] [--deploy]
    area deploy <name> [--yes]

Common: [--backend acp|llm] [--model M] [--spec-iters K] [--build-iters K] [--yes]
"""
from __future__ import annotations

import argparse


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
    sp.add_argument("--deploy", action="store_true", help="deploy after a green build")
    sp.add_argument("--yes", action="store_true", help="skip the deploy human gate")


def _finish(res, args) -> int:
    status = "✅ GREEN" if res.passed else "❌ NOT green"
    print(f"\n[area] {status} — {res.name}")
    print(f"[area] spec: {res.spec_dir}\n[area] app : {res.app_dir}")
    if res.passed and args.deploy:
        from area.deploy import deploy_with_gate

        ok, _ = deploy_with_gate(res.app_dir, confirm=_confirm_fn(args.yes))
        return 0 if ok else 1
    return 0 if res.passed else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="area", description="AREA — internal AI software factory")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="Flow A: requirement -> spec -> app")
    r.add_argument("requirement", help="natural-language requirement, in quotes")
    _add_common(r)

    c = sub.add_parser("clone", help="Flow B: reverse-engineer a sample app -> spec -> app")
    c.add_argument("source", help="git URL | local path | http(s) URL of the sample app")
    c.add_argument("--kind", default="auto", choices=["auto", "repo", "path", "url"])
    _add_common(c)

    d = sub.add_parser("deploy", help="Deploy a built app to Cloudflare (human gate)")
    d.add_argument("name")
    d.add_argument("--yes", action="store_true", help="skip the human gate")

    args = p.parse_args(argv)

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
            args.source, name=args.name or "clone", kind=args.kind, target=args.target,
            backend=args.backend, model=args.model,
            spec_iters=args.spec_iters, build_iters=args.build_iters,
        )
        return _finish(res, args)

    if args.cmd == "deploy":
        from area.deploy import deploy_with_gate
        from area.pipeline import WORKSPACE

        app_dir = WORKSPACE / "apps" / args.name
        if not app_dir.exists():
            print(f"[area] no app at {app_dir}")
            return 1
        ok, _ = deploy_with_gate(app_dir, confirm=_confirm_fn(args.yes))
        return 0 if ok else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
