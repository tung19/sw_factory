# Example — `taskboard`

**A real app AREA built from one sentence, start to finish, with the oracle-loop
enforced in code.** This is committed *evidence*: the spec, the independent locked
oracle, the generated source, and the gate results — exactly what the factory
produces.

## The requirement (what went in)

> A multi-page team task board. Users sign up and log in (passwords hashed, never
> plaintext). Each user sees only their own boards. A user can create boards, add
> tasks (todo/doing/done) and change a task's status. Data persists across a server
> restart. Pages: login/signup, a boards list, and a board detail page.

Built with: `area run "<the requirement>" --name taskboard --target plain --tdd`

## The oracle-loop (how it was built, and why you can trust it)

1. **Spec** — [`SPEC/spec.yaml`](SPEC/spec.yaml) + [`SPEC/acceptance.yaml`](SPEC/acceptance.yaml)
   (12 acceptance criteria) + [`SPEC/assumptions.yaml`](SPEC/assumptions.yaml)
   (the guesses it made, surfaced for the human) + [`SPEC/design.md`](SPEC/design.md).
2. **Independent locked oracle** — the acceptance tests under
   [`__tests__/_holdout/`](__tests__/_holdout/) were authored by a *separate* agent
   from the spec only, then **checksum-locked** ([`SPEC/holdout.lock`](SPEC/holdout.lock)).
   The build agent could never edit them — it had to make the *frozen* tests pass by
   writing app code. *(The same reasoning never both writes AND grades the code.)*
3. **Build to green** — the generated source under [`app/`](app/) + [`lib/`](lib/)
   was written until the locked holdout passed.
4. **Gates** — all 7 ran after the build.
5. **Provenance** — [`SPEC/provenance.json`](SPEC/provenance.json) attests
   {spec digest → gates passed → artifact sha} so a deploy can prove the build
   wasn't modified after gating.

## The evidence (results)

| Check | Result |
|-------|--------|
| Locked holdout (`npx vitest run __tests__/_holdout`) | ✅ **18/18** — covers AC-1 … AC-12 |
| Everything `npm test` runs | ✅ **73** — the 18 above plus 55 chaos tests; `vitest.config.mts` includes all of `__tests__/**`, so `npm test` has never printed 18 |
| Holdout integrity | ✅ checksums identical to `holdout.lock` — oracle never touched |
| `audit` (tsc + `npm audit` + secrets) | ✅ **0 vulnerabilities** |
| `nfr` (bundle / deps / weight) | ✅ within budget |
| `perf` (live load) | ✅ p50 ~19 ms · ~505 req/s · 0 errors |
| `e2e` (Playwright, real browser) | ✅ one spec per AC — [`e2e/`](e2e/) — incl. signup→login, per-user isolation, restart-durability |
| `chaos` (adversarial inputs) | ✅ hardened — [`__tests__/_chaos/`](__tests__/_chaos/) |
| Cost / time | **$5.19** · ~15 min |

Notably, the **e2e gate needed no app fixes** — the oracle-loop produced a
*live-correct* auth app on the first try.

## Run it yourself — **no Claude key, no cost**

From the repo root:

```bash
area demo taskboard      # installs, builds, serves, opens your browser
```

or manually:

```bash
cd examples/taskboard
npm install
npm run build && npm start     # http://localhost:3000  (or the port it prints)
```

The durable store is `node:sqlite` at `./data/taskboard.db` (created on first run).

## What to read

- [`SPEC/`](SPEC/) — the spec, acceptance criteria, assumptions, design, the lock, the provenance.
- [`__tests__/_holdout/`](__tests__/_holdout/) — the **independent oracle** (the locked tests).
- [`app/`](app/) + [`lib/`](lib/) — the generated application (3 pages, auth, per-user isolation, durable sqlite).
- [`e2e/`](e2e/) — the end-to-end specs, one per acceptance criterion.
