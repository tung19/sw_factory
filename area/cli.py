"""area CLI.

Usage:
    area run "<requirement>" [--name N] [--backend acp|llm] [--model M]
                             [--spec-iters K] [--build-iters K]
"""
from __future__ import annotations

import argparse


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="area", description="AREA — internal AI software factory"
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="Flow A: requirement -> spec -> Next.js app")
    r.add_argument("requirement", help="natural-language requirement, in quotes")
    r.add_argument(
        "--name", default="app", help="project name / output folder (default: app)"
    )
    r.add_argument(
        "--backend",
        default="acp",
        choices=["acp", "llm"],
        help="acp = Claude Code login (no key); llm = LLM_API_KEY",
    )
    r.add_argument("--model", default=None, help="model / alias (optional)")
    r.add_argument("--spec-iters", type=int, default=3)
    r.add_argument("--build-iters", type=int, default=3)

    args = p.parse_args(argv)

    if args.cmd == "run":
        from area.pipeline import run_pipeline

        res = run_pipeline(
            args.requirement,
            name=args.name,
            backend=args.backend,
            model=args.model,
            spec_iters=args.spec_iters,
            build_iters=args.build_iters,
        )
        status = "✅ GREEN" if res.passed else "❌ NOT green"
        print(f"\n[area] {status} — {res.name}")
        print(f"[area] spec: {res.spec_dir}")
        print(f"[area] app : {res.app_dir}")
        return 0 if res.passed else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
