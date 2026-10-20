# tools/ — deterministic scripts Claude Code runs

The oracle-loop (in the root `CLAUDE.md`) is driven by Claude Code itself. These are
the **deterministic**, non-agent steps it invokes — they measure/enforce/act, they do
NOT reason. Each reuses logic already in the `area` package where possible.

| Script | Does | Status |
|---|---|---|
| `lock-holdout.sh <name>` | Checksum + freeze the holdout oracle (independence) | ✅ |
| `verify-holdout-intact.sh <name>` | Fail if the holdout changed since locking | ✅ |
| `gate.sh <name> [--audit --nfr --e2e --chaos]` | Run the verification gates (wraps `area.verify`) | ▶ next |
| `provenance.sh <name> [--verify]` | Record / check SLSA-style provenance (wraps `area.provenance`) | ▶ next |
| `deploy.sh <name>` | Provision + deploy to your Cloudflare/Vercel (wraps `area.deploy`) | ▶ next |

The `area` CLI (`.venv/bin/area`) still holds the deterministic engines — `audit`,
`provenance`, `deploy`, the `verify` gates. The `▶ next` scripts are thin wrappers over
those (no ACP / no agent-driving), so the native loop reuses them without the slow
coordinator/runner/ACP layers (which now live on the `saas-coordinator-runner` branch).
