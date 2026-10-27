<!-- Thanks for contributing to AREA. Keep the oracle-loop spine intact. -->

## What & why
<!-- What does this change, and why? Explain the reasoning, not just the diff. -->

## Checklist
- [ ] Tests added/updated for the change (the suite is agent-free — stub the agent).
- [ ] `python -m pytest` is green locally.
- [ ] `ruff check area tests` is clean.
- [ ] If this touches a gate or the engine seam: I did **not** weaken oracle
      independence (locked holdout, checksum, guard hook) or turn an LLM-judgement
      check into a hard block without measuring its false-positive rate.
- [ ] If this adds an agent call: it goes through `area.engine` (no direct
      `claude -p` / SDK import outside `area/engine`).
- [ ] Docs updated if behavior/flags changed (`README` / `docs/ARCHITECTURE.md` /
      `CONTRIBUTING.md`).

## How I verified
<!-- Dogfood evidence beats logic-only claims — "oracle green", a demo run, etc. -->
