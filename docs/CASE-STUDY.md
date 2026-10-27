# Case study — building `taskboard` from one sentence

How AREA turned a plain-language requirement into a working, gated, auditable app,
and *why you can trust the "done"*. Every artifact below is committed under
[`examples/taskboard/`](../examples/taskboard/) — you can read it, and run it with
`area demo taskboard` (no Claude key, no cost).

## 1 · The ask

> A multi-page team task board. Users sign up and log in (passwords hashed, never
> plaintext). Each user sees only their own boards. Create boards, add tasks
> (todo/doing/done), change a task's status. Data persists across a restart.
> Pages: login/signup, a boards list, a board detail page.

```bash
area run "<that requirement>" --name taskboard --target plain --tdd
```

## 2 · Spec — the requirement, made structured

The spec stage produced [`SPEC/spec.yaml`](../examples/taskboard/SPEC/spec.yaml)
(a `User`/`Board`/`Task` data model) and
[`SPEC/acceptance.yaml`](../examples/taskboard/SPEC/acceptance.yaml) — **12
acceptance criteria**, each a concrete given/when/then:

```yaml
- id: AC-1
  feature: signup
  given: a visitor is on the combined login/signup page and no account exists for the email
  when: they submit the signup form with a valid email and password
  then: an account is created, they are logged in, and they land on the boards-list page
```

The guesses it had to make are recorded in
[`SPEC/assumptions.yaml`](../examples/taskboard/SPEC/assumptions.yaml) and surfaced
to the human — the factory doesn't hide where it filled gaps.

## 3 · The independent, locked oracle (this is the point)

Before any app code existed, a **separate agent** wrote the acceptance tests from
the spec *only*, under
[`__tests__/_holdout/`](../examples/taskboard/__tests__/_holdout/). They open each
test's own throwaway database and drive the app through its **public surface**
(`lib/auth`, `lib/boards`, `lib/tasks`) — never its internals:

```ts
// LOCKED HOLDOUT — independent acceptance oracle (authored from the spec only).
// Covers AC-11. Do not edit after locking.
beforeAll(async () => {
  process.env.TASKBOARD_DB = path.join(os.tmpdir(), `taskboard-holdout-isolation-${crypto.randomUUID()}.db`)
  auth   = await import('../../lib/auth')
  boards = await import('../../lib/boards')
  tasks  = await import('../../lib/tasks')
})
describe('AC-11 user-isolation', () => { /* user A can never see user B's boards */ })
```

Then the suite was **checksum-locked** →
[`SPEC/holdout.lock`](../examples/taskboard/SPEC/holdout.lock). From that point the
build agent **could not edit it** (a PreToolUse hook blocks it; a verify step
re-checks the checksums). *The same reasoning never both wrote AND graded the code.*

## 4 · Build to green

The build agent wrote the app ([`app/`](../examples/taskboard/app/) — 3 pages,
server actions; [`lib/`](../examples/taskboard/lib/) — auth, password hashing,
sessions, a `node:sqlite` store) until the **frozen** suite passed — and the gate
confirmed the suite actually *ran*, not merely exited 0.

## 5 · The gates (evidence)

| Gate | Result |
|------|--------|
| locked holdout | ✅ **18/18** (AC-1 … AC-12) · checksums identical to the lock |
| `audit` (tsc + npm audit + secrets) | ✅ **0 vulnerabilities** |
| `nfr` (bundle / deps / weight) | ✅ within budget |
| `perf` (live load) | ✅ p50 ~19 ms · ~505 req/s · 0 errors |
| `e2e` (Playwright, real browser) | ✅ one spec per AC — signup→login, isolation, restart-durability |
| `chaos` (adversarial inputs) | ✅ hardened |
| cost / time | **$5.19 · ~15 min** |

The telling detail: **the e2e gate needed no app fixes.** The oracle-loop produced
a *live-correct* auth app on the first try — the opposite of "logic-green but the
live signup is broken", which is why e2e is now mandatory before deploying an auth
app.

## 6 · Provenance

[`SPEC/provenance.json`](../examples/taskboard/SPEC/provenance.json) attests the
build: `artifactDigest: sha256:9d5b25bd…` over the app source. A later deploy
verifies this and **refuses on a mismatch** — you can't tamper with the artifact
after it was gated.

## What this demonstrates

- **Independence, enforced in code** — not "the AI says it's done", but "an
  independent, frozen test suite passed, and it provably ran."
- **Auditable** — requirement → spec → locked oracle → gates → provenance, each a
  committed artifact.
- **Honest about ambiguity** — the assumptions are recorded, and when a requirement
  is *un*buildable the factory stops and asks (see the sidebar below).

### Sidebar — when the factory says "no" (and reframes)

In a separate test, a `.docx` was dropped in. AREA extracted it and found it asked
to **log in to a real government tax portal and pull filed declarations** — an
integration AREA cannot and should not build (no API, real credentials, legal/ToS).
It **stopped and said so**, then (with the human's OK) reframed the request into a
*self-contained* invoice/declaration manager with mock data, and built that green.
Refusing the un-buildable, and proposing a buildable version, is part of the
discipline — not a failure.

## See it yourself

```bash
area demo taskboard      # install → build → serve → open your browser (keyless)
```

Read the artifacts: [`SPEC/`](../examples/taskboard/SPEC/) (spec, acceptance,
assumptions, design, lock, provenance) · the
[locked oracle](../examples/taskboard/__tests__/_holdout/) · the
[generated app](../examples/taskboard/app/) · the
[e2e specs](../examples/taskboard/e2e/).
