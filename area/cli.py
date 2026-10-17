"""area CLI.

    area run "<requirement>" [--name N] [--target cloudflare|plain]
                             [--backend acp|llm] [--model M] [--deploy] [--yes]
    area deploy <name> [--yes]
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


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="area", description="AREA — internal AI software factory"
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="Flow A: requirement -> spec -> Next.js app")
    r.add_argument("requirement", help="natural-language requirement, in quotes")
    r.add_argument("--name", default="app", help="project name / output folder")
    r.add_argument(
        "--target", default="cloudflare", choices=["cloudflare", "plain"],
        help="cloudflare = Workers (vinext); plain = vanilla Next.js",
    )
    r.add_argument(
        "--backend", default="acp", choices=["acp", "llm"],
        help="acp = Claude Code login (no key); llm = LLM_API_KEY",
    )
    r.add_argument("--model", default=None, help="model / alias (optional)")
    r.add_argument("--spec-iters", type=int, default=3)
    r.add_argument("--build-iters", type=int, default=3)
    r.add_argument("--deploy", action="store_true", help="deploy after a green build")
    r.add_argument("--yes", action="store_true", help="skip the deploy human gate")

    d = sub.add_parser("deploy", help="Deploy a built app to Cloudflare (human gate)")
    d.add_argument("name", help="project name (folder under workspace/apps/)")
    d.add_argument("--yes", action="store_true", help="skip the human gate")

    args = p.parse_args(argv)

    if args.cmd == "run":
        from area.pipeline import run_pipeline

        res = run_pipeline(
            args.requirement,
            name=args.name,
            target=args.target,
            backend=args.backend,
            model=args.model,
            spec_iters=args.spec_iters,
            build_iters=args.build_iters,
        )
        status = "✅ GREEN" if res.passed else "❌ NOT green"
        print(f"\n[area] {status} — {res.name}")
        print(f"[area] spec: {res.spec_dir}")
        print(f"[area] app : {res.app_dir}")
        if res.passed and args.deploy:
            from area.deploy import deploy_with_gate

            ok, url = deploy_with_gate(res.app_dir, confirm=_confirm_fn(args.yes))
            return 0 if ok else 1
        return 0 if res.passed else 1

    if args.cmd == "deploy":
        from area.deploy import deploy_with_gate
        from area.pipeline import WORKSPACE

        app_dir = WORKSPACE / "apps" / args.name
        if not app_dir.exists():
            print(f"[area] no app at {app_dir}")
            return 1
        ok, url = deploy_with_gate(app_dir, confirm=_confirm_fn(args.yes))
        return 0 if ok else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
