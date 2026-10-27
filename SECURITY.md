# Security

AREA is a **local-first** developer tool: it runs on your machine, drives coding
agents, and deploys to **your** Cloudflare/Vercel with **your** credentials.
Nothing (code or secrets) leaves your machine except a deploy you explicitly run.

## Model & boundaries

- **No central service.** Each user runs the factory themselves; there is no
  shared server holding anyone's code or keys.
- **Deterministic gates block; LLM-judgement gates are advisory** until `--strict`.
  See `docs/ARCHITECTURE.md` (the 9 gates) and `CONTRIBUTING.md` (the rules).
- **Independent, locked oracle.** Acceptance tests are authored by a separate agent
  from the spec and checksum-locked, and the gate confirms the locked suite actually
  ran. A PreToolUse hook (`tools/hooks/guard_holdout.py`) *blocks* edits in a Claude
  Code session rooted in this repo; for the autonomous build agent the lock is
  detect-and-revert, not prevent (see `docs/ARCHITECTURE.md`).
- **Provenance before deploy.** A build is attested (spec digest → gates → artifact
  sha); a provenance **mismatch blocks the deploy** (tamper-after-gating is refused).
- **Secrets never hit argv/logs.** Deploy tokens are passed via stdin/env, never on
  the command line; `safe_name()` sanitizes every name used in a filesystem path;
  `area export --repo` and `area clone` reject git transport-helper RCE vectors.
- **Dashboard is auth-gated** (token, `127.0.0.1` by default). Disabling auth
  (`AREA_GUI_NO_AUTH=1`) exposes full local control — only for trusted local use.

- **Credentials are screened on the way IN**, not only out. Material copied from an
  untrusted reference, an upload, or a fetched page is redacted before the agent reads
  it (`area/screen.py`); the original evidence under `_sample/` is left byte-exact and
  reported instead.
- **The factory itself is pinned during a run.** `tools/verify-factory-intact.sh`
  checksums `area/`/`tools/`/`skills/` before a build and fails it if they changed, so
  a gate cannot have graded with modified code.
- **Runs are bounded and stoppable.** Every agent/build/provider subprocess has a wall
  clock and is killed as a process group; a dashboard job can be cancelled
  (`DELETE /api/jobs/{id}`).

## Known gaps (deliberate, not oversights)

AREA was measured against *The Secure Software Factory* (Agent Baseline v1) — see
**[docs/secure-factory-gap-assessment.md](docs/secure-factory-gap-assessment.md)** for
the full gap table and backlog. The short version of what is **not** defended:

- **No sandbox boundary.** The build agent runs as a subprocess on your host with your
  file access — there is no container, VM or syscall policy. Isolation is your machine.
- **No network boundary.** There is no egress proxy: the agent reaches whatever your
  host can reach, and `npm install` fetches from the public registry with no admission
  point or version cooldown.
- **No per-agent identity or task-scoped credentials.** Deploy secrets are stripped
  from the agent's environment, but they live in yours; there is no authorization
  service issuing short-lived, task-bounded grants.
- **The attestation is not tamper-evident in the strong sense.** It is unsigned and
  written inside the app's own `.area/`, a tree the build agent can reach.

These are enterprise, multi-tenant controls; for a single-operator local factory they
are the wrong size. They become prerequisites if the hosted coordinator/runner
(`docs/adr/0002-coordinator-runner-saas.md`) is ever built — **do not run AREA as a
shared service without them.**

## What the agent can and can't do

The build agent runs with your Claude session and edits files under the app's
workspace. It cannot edit a locked holdout (hook-enforced), and deploys require an
explicit human gate. REA (Tier-2 reverse-engineering) is opt-in (`--rea`), pinned
to an exact version, and must only be pointed at software you are authorized to
analyze.

## This repo has been security-audited

The factory code was reviewed by independent audit passes (correctness, security,
architecture). Confirmed findings — oracle-must-run, audit-gate blind spots, a
clone-source RCE guard, provenance-blocks-by-default, token-in-URL leakage, engine-
seam unification, and more — were remediated. See the commit history (`Audit fix`
commits) and `docs/UPGRADE-PLAN.md`.

## Reporting a vulnerability

Please report security issues **privately**, not in a public issue:
open a GitHub **Security advisory** on this repository
(`Security` → `Report a vulnerability`). Include repro steps and impact. We aim to
acknowledge within a few days. Because AREA is local-first and single-user, most
issues are gate-soundness or local-privilege concerns rather than remote exploits —
those are still welcome.
