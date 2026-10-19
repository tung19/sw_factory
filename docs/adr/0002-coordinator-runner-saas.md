# ADR 0002 — Coordinator + Runner (orchestrate-only SaaS)

- **Status:** Accepted — 2026-10-19 (building P0)
- **Supersedes:** the distribution stance of [ADR 0001](0001-local-first-byo-everything.md).
  The local-first install becomes the **runner**; a thin hosted **coordinator**
  is added on top.
- **Deciders:** Tung (owner)

## Context

Owner's goal, in their words: *"đẩy về hết trên hạ tầng user — tôi chỉ là nơi
điều phối."* I.e. a SaaS where a user opens a web URL, logs in / connects their
Claude, and everything runs on **the user's own infrastructure**. The owner is
only the **coordinator**, never the executor.

Hard constraint: an AREA job runs real code (npm, git, build, deploy) and holds
deploy credentials. A browser cannot do that. So "everything on the user's
infra" means the execution runs on a process the user controls — not the host's
server, not the browser. This is the **self-hosted runner** pattern (GitHub
Actions runners, GitLab runners, Terraform Cloud agents).

## Decision

Split AREA into two planes:

- **Coordinator (control plane) — the owner hosts this.** A thin web service:
  user accounts + login, pairs a user with their runner, serves the dashboard
  UI, and **relays** commands and log/status between the UI and the runner. It
  runs **no agents**, stores **no user code**, and holds **no user secrets**.
  Because it only coordinates, it can live on **Cloudflare Workers** (Durable
  Objects for the live relay/websocket, D1 for accounts/metadata) — cheap,
  possibly free-tier.

- **Runner (data plane) — the user runs this on their own infra.** `area runner`
  connects **outbound** to the coordinator, authenticates as the user, receives
  jobs, executes them through AREA's existing pipeline on the user's machine/VM,
  and streams logs/status back. It uses the **user's Claude** (keyless Claude
  Code, or their API key) and the **user's Cloudflare/Vercel** for deploys.

```
   OWNER hosts (orchestrate only)          USER's infra (executes everything)
 ┌────────────────────────────┐          ┌──────────────────────────────────┐
 │ COORDINATOR                │          │ AREA RUNNER  (`area runner`)       │
 │  web UI + auth             │◀────────▶│  pipeline: spec→oracle→build→      │
 │  pair user ↔ runner        │  relay   │           gates→deploy             │
 │  relay commands + logs     │ (ws, the │  Claude = USER's                   │
 │  (Cloudflare Workers + DO) │  runner  │  deploy = USER's CF/Vercel         │
 │  NO agents / NO secrets    │  dials   │  secrets NEVER leave here           │
 └────────────────────────────┘  out)    └──────────────────────────────────┘
```

## How it works

1. **Pairing.** User signs up on the coordinator → gets a one-time pairing
   token. They install + start the runner: `area runner --connect <coord-url>
   --token <pairing-token>`. The runner registers and stays connected.
2. **Outbound only.** The runner **dials out** to the coordinator over a
   websocket, so the user opens **no inbound ports** and needs no public IP.
3. **Command flow.** In the web UI the user types a command (run / iterate /
   deploy / chat). Coordinator → relays the job to that user's runner → runner
   executes locally through the existing `area` pipeline → streams `[area]`
   log lines + status back → UI shows the live pipeline (the dashboard we
   already have).
4. **Credentials stay put.** The user's Claude + CF/Vercel creds live only on
   the runner. The coordinator relays bytes; it never sees or stores them.

## Security model

- **No shared execution host** → the per-user sandbox problem disappears (each
  runner is the user's own isolated infra).
- **Coordinator holds no secrets and no user code** → a coordinator breach can't
  leak a user's keys or source. Worst case it can relay a malicious command to a
  runner, so: runner only accepts jobs for its paired account, commands are a
  **fixed typed set** (run/clone/intake/iterate/deploy/export/chat — no arbitrary
  shell), and destructive actions (deploy) keep the human gate.
- **Transport:** TLS everywhere; the pairing token is single-use and scoped to
  one runner; rotate on compromise.

## Reused vs new

| Piece | Status | Work |
|---|---|---|
| Engine (spec/oracle/build/gates/deploy), JobManager, pipeline | ✅ reuse | none |
| Dashboard UI (`area/web/static`) | ✅ reuse | point its fetch/SSE at the relay instead of local `/api` |
| **`area runner` mode** | 🆕 | ws client + typed job protocol + stream back; wraps existing pipeline calls |
| **Coordinator service** | 🆕 | Workers + Durable Object (relay/session) + D1 (accounts, pairings); serves UI; relays. No agent code |
| **Pairing/auth** | 🆕 | signup/login, per-user pairing token, runner registration |

## Consequences

**Positive**
- Owner is purely a coordinator: ~0 compute/LLM/deploy cost, holds no secrets,
  no multi-tenant sandbox to build or audit.
- Everything (compute, LLM, deploy, data) on the user's infra, their accounts.
- Coordinator is light enough for Cloudflare Workers (answers "host on
  Cloudflare" cleanly — the *coordinator*, not the factory).

**Trade-offs (accepted)**
- The user installs + runs a runner **once** (self-hosted-runner reality). Make
  it one-command / one-click-deploy to their cloud.
- The owner now runs a (small) service with uptime/auth responsibility — more
  than ADR 0001's static page, far less than a full execution SaaS.
- Offline runner = that user's jobs can't run (expected; it's their infra).

## Open questions / risks

1. **Claude on the runner:** keyless Claude Code works on the user's machine; on
   a headless user VM they may need their API key (`backend="llm"`). Support both.
2. **Relay tech:** Cloudflare Durable Objects for the websocket session is the
   likely fit; validate limits (message size for log streaming, connection
   duration). Fallback: a tiny Node relay on any small host.
3. **Job protocol:** define a small, versioned, typed schema (job kinds + params
   + log/stop/done events). No arbitrary commands over the wire.
4. **Runner packaging/update:** install-once + self-update; or a container image
   the user deploys to their own cloud.

## Implementation roadmap (MVP → beyond)

- **P0 — Prove the loop (thinnest slice).** `area runner --connect` dials a
  minimal relay; UI sends ONE job kind (`run`), runner executes via the existing
  pipeline, logs stream back to the UI. Single hard-coded pairing. *Goal: one
  end-to-end job over the wire.*
- **P1 — Full job set + live pipeline.** All kinds (run/clone/intake/iterate/
  deploy/export/chat) over the typed protocol; the existing live pipeline + chat
  UI driven through the relay.
- **P2 — Accounts + pairing.** Signup/login on the coordinator, per-user pairing
  tokens, runner registration, multiple users each to their own runner.
- **P3 — Harden + package.** Reconnect/backpressure, auth hardening, one-command
  runner install + self-update (or container), coordinator on Cloudflare
  Workers + DO + D1, docs.
- **Later.** Teams, audit trail (tie into the AI-DLC evidence trail), usage
  metering (jobs, not tokens — tokens are the user's).

## Recommendation

Approve this direction, then build **P0** as a throwaway-thin vertical slice to
de-risk the relay + runner protocol before investing in accounts/packaging.
