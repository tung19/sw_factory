# ADR 0001 — Local-first, BYO-everything (not hosted multi-tenant)

- **Status:** Accepted — 2026-10-19
- **Deciders:** Tung (owner)
- **Context tag:** distribution / hosting / security

## Context

AREA is an autonomous software factory: LLM agents turn a requirement (or a
natural-language command) into a working, tested app and deploy it. An agent
run reads/writes a workspace, executes `npm`/`git`/build/test, and deploys to
Cloudflare/Vercel — i.e. it runs **arbitrary code** and holds **deploy
credentials**.

The question: how do multiple users get to *use* AREA? Three shapes were on the
table, and they differ mostly in **where the compute runs** and **whose accounts
pay**.

## Options considered

1. **Hosted multi-tenant SaaS** — the owner runs AREA on a central server; users
   just open a URL. Rejected: the owner pays for the server **and** the LLM
   tokens, and — worse — every user's agent runs arbitrary code on a shared box,
   so the owner must build strict **per-user sandboxing/isolation** (a container
   + isolated workspace + locked-down deploy creds per user). High cost, high
   security burden.

2. **BYOK on the owner's server** — users bring their own Claude API key, but the
   compute still runs on the owner's server. Rejected: removes the owner's *LLM*
   cost, but **not** the server cost and **not** the per-user sandbox burden.
   "User's side" here is only billing, not isolation.

3. **Tunnel to the owner's machine** (Cloudflare quick tunnel → laptop).
   Rejected for anything but a demo: tied to one machine, ephemeral URL, dies
   when the laptop sleeps, and still single-tenant.

4. **Local-first, BYO-everything** — each user runs AREA on **their own machine**,
   against **their own accounts** (Claude, Cloudflare/Vercel). *(Chosen.)*

## Decision

**Distribute AREA as a local-first tool.** Each user installs and runs it on
their own machine; all compute, source code, and credentials stay on the user's
side:

| Component | Where it runs / whose account |
|---|---|
| Agent compute, source code, workspace | the **user's machine** |
| LLM (Claude) | the **user's** Claude (keyless Claude Code, or their API key) |
| Deploy | the **user's** Cloudflare/Vercel account |
| **Owner's recurring cost** | **≈ 0** (no compute, no LLM, no deploy) |

The owner's only cloud footprint is a **static distribution/landing page**
(Cloudflare Pages) plus docs — not a running service.

```
Owner's Cloudflare : static landing + install docs      (cheap, trivial to deploy)
Each user's machine: `area gui` → their Claude + their Cloudflare/Vercel
```

## Why

- **Per-user isolation is free.** There is no shared server, so "user A must not
  touch user B's files / a malicious prompt must not wreck the host" simply does
  not arise — each user is their own machine.
- **Owner cost ≈ 0** and **no secrets custody**: the owner never holds a user's
  Claude key or deploy creds.
- **Security by construction**: agent-generated code only ever runs on the
  machine of the person who asked for it.
- **It matches the code we already have**: keyless Claude Code (ACP), a local
  `workspace/`, local `area gui`, and `area export` to the user's own repo.

## Consequences

**Positive**

- Owner runs a static page, not a platform. No server ops, no scaling, no
  multi-tenant security review.
- Users fully own their workspace, generated repos (`area export`), and
  deployments.

**Trade-offs (accepted)**

- Users **install and run locally** — it is not "just open a URL". Onboarding is
  per-install; updates are pull-based (`git pull` / re-install).
- Each user needs their own Claude and Cloudflare/Vercel accounts.
- No central view across users (by design).
- If an always-on, zero-install hosted product is ever wanted, that is a separate
  project (a VM running AREA with `backend="llm"` + per-user sandboxes) and would
  re-introduce every burden listed under options 1–2. This ADR deliberately does
  not take that path now.

## Implementation

- **Packaging:** `scripts/install.sh` (one-command bootstrap) + `area doctor`
  (checks Python/Node/git/gh/Claude Code and prints what is missing).
- **Distribution:** a static landing page under `site/` for Cloudflare Pages.
- **Per-user accounts:** the user authenticates their own Claude Code (or exports
  `ANTHROPIC_API_KEY`) and their own `cf`/`vercel` — AREA already reads these.
