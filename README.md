# AREA — autonomous software factory

Give it a requirement in plain language; it produces a **working, gated,
optionally-deployed app** — and it proves the work with an independent, locked
acceptance oracle, not a vague "looks done". Runs **local-first**: on your machine,
with your Claude and your Cloudflare/Vercel. Nothing leaves your box.

```
requirement → spec → LOCKED independent oracle → build-to-green → 7 gates → provenance → deploy
```

---

## See it work in 3 minutes — no Claude key, no cost

```bash
git clone https://github.com/tung19/sw_factory && cd sw_factory
make setup          # or: bash scripts/install.sh
area demo taskboard # install → build → serve → opens your browser
```

`taskboard` is a **real app the factory built** (multi-page, signup/login with
hashed passwords, per-user isolation, durable sqlite). It's committed under
[`examples/taskboard/`](examples/taskboard/) with its **spec, the independent
locked oracle, and the gate evidence** (18/18 holdout, 0 vulns, e2e on a real
browser, ~505 req/s). Read its [README](examples/taskboard/README.md) to see the
oracle-loop end to end.

## Build your own app (the golden path)

This is the one pipeline everything serves:

```bash
area doctor                                   # check your setup once
area run "a todo app: add/list/complete/delete tasks, filter by status, persist" \
         --name todo --target plain --tdd     # lock an independent oracle, build to green
# add gates:  --audit --e2e --chaos --all     # (e2e is forced before deploying an auth app)
# deploy:     area deploy todo                 # to YOUR Cloudflare/Vercel (needs your token)
area trace todo                               # the end-to-end audit trail
```

`--tdd` authors the acceptance tests **first** (by a separate agent, from the spec
only), **checksum-locks** them, then builds app code until that frozen suite
passes. The builder can never edit the oracle — so "green" means the independent
tests actually passed. See **[ADR-0003](docs/adr/0003-oracle-loop-independence.md)**.

## Setup & requirements

- **Python ≥ 3.12**, **Node**, **git** — and **Claude** (Claude Code keyless, or
  `export ANTHROPIC_API_KEY=…`). Cloudflare/Vercel only when you deploy.
- `make setup` creates the venv (via `uv`), installs the in-tree engine, and runs
  `area doctor`. `area doctor` re-checks anytime.
- **Keep generated apps out of the repo:** `export AREA_WORKSPACE=~/area-generated`
  (apps/specs then live there instead of in the checkout).

## Why local-first

AREA runs on **your** machine with **your** accounts; there is no central service
holding anyone's code or secrets. Deploys go to your infra and require an explicit
gate. See [ADR-0001](docs/adr/0001-local-first-byo-everything.md) and
[SECURITY.md](SECURITY.md).

## Beyond the golden path (advanced / optional)

- **Dashboard:** `area gui` — a web UI for the same pipeline (upload a doc, watch
  the stages, iterate, see metrics).
- **Flow B — Clone:** `area clone <url|repo|path>` — reverse-engineer a reference
  app → spec → behavioral-parity build. RE Tier-1 is built-in; **Tier-2 (`--rea`)**
  is opt-in, pinned, and only for software you're authorized to analyze.
- **Intake / Inception:** `area intake <ai-dlc-artifacts>` and `area inception
  "<req>"` — a governed front-end that shapes the oracle before building.
- **Iterate:** `area iterate <app> "<change>"` — fold a change into the spec,
  re-lock the oracle, rebuild.

## Docs

- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — the system map (spine, pipeline, the 7 gates, modules). *Start here to understand the code.*
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — setup, tests, how to add a gate/backend.
- **[docs/CASE-STUDY.md](docs/CASE-STUDY.md)** — building `taskboard` from one sentence, with the real artifacts. *Proof it works.*
- **[CLAUDE.md](CLAUDE.md)** — the rules the build agent follows. **[SECURITY.md](SECURITY.md)** · **[CHANGELOG.md](CHANGELOG.md)**.
- **[docs/UPGRADE-PLAN.md](docs/UPGRADE-PLAN.md)** · **[PLAN.md](PLAN.md)** — roadmap & status.

## Layout

```
area/        the factory: intake · re · spec · engine (seam to the SDK) · verify (7 gates) · deploy · inception · web (dashboard)
examples/    REAL apps the factory built (committed: source + spec + locked oracle + evidence)
tools/       deterministic shell gates (lock/verify-holdout, gate, provenance)
docs/        ARCHITECTURE, ADRs, UPGRADE-PLAN
vendor/      the engine (OpenHands SDK), vendored in-tree
workspace/   default output (apps/<name> + specs/<name>) — override with AREA_WORKSPACE
```
