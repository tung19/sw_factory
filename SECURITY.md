# Security

AREA is a **local-first** developer tool: it runs on your machine, drives coding
agents, and deploys to **your** Cloudflare/Vercel with **your** credentials.
Nothing (code or secrets) leaves your machine except a deploy you explicitly run.

## Model & boundaries

- **No central service.** Each user runs the factory themselves; there is no
  shared server holding anyone's code or keys.
- **Deterministic gates block; LLM-judgement gates are advisory** until `--strict`.
  See `docs/ARCHITECTURE.md` (the 7 gates) and `CONTRIBUTING.md` (the rules).
- **Independent, locked oracle.** Acceptance tests are authored by a separate agent
  from the spec and checksum-locked; a PreToolUse hook (`tools/hooks/guard_holdout.py`)
  blocks edits to them, and the gate now also confirms the locked suite actually ran.
- **Provenance before deploy.** A build is attested (spec digest → gates → artifact
  sha); a provenance **mismatch blocks the deploy** (tamper-after-gating is refused).
- **Secrets never hit argv/logs.** Deploy tokens are passed via stdin/env, never on
  the command line; `safe_name()` sanitizes every name used in a filesystem path;
  `area export --repo` and `area clone` reject git transport-helper RCE vectors.
- **Dashboard is auth-gated** (token, `127.0.0.1` by default). Disabling auth
  (`AREA_GUI_NO_AUTH=1`) exposes full local control — only for trusted local use.

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
