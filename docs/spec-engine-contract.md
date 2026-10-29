# The spec-engine ↔ factory contract

**For engineers building a spec engine** — the front-end half that turns a user's raw
request (1-line idea / user story / full PRD / technical constraints) into something AREA
can build autonomously. This document is the contract your output must satisfy so the two
halves connect.

> **One line:** the spec engine emits **one invariant artifact**; the factory consumes it;
> `validate_cross` is the weld. **Input granularity drives *confidence*, never *schema*.**

The authority for every field below is [area/spec/models.py](../area/spec/models.py) and
the gate in [area/spec/extract.py](../area/spec/extract.py) (`_spec_verifier`). If this doc
and that code ever disagree, the code wins — and `tools/validate-spec.sh` runs the code, so
use it, don't trust prose.

---

## 0 · The seam — where you plug in

Your engine writes an artifact into `workspace/specs/<name>/`, then the factory builds from
it. Two supported entry points, both skip the factory's own LLM extraction:

| Entry point | You provide | Command |
|---|---|---|
| **`--use-spec`** | `spec.yaml` + `acceptance.yaml` (+ optional `assumptions.yaml`) | `area run --name <name> --use-spec` |
| **`area intake`** | a dir/file of AI-DLC Inception artifacts (`.md/.yaml/.json`) | `area intake <artifacts> --name <name>` |

`area intake` still runs an LLM adapter ([area/intake/aidlc.py](../area/intake/aidlc.py)) to
translate the artifacts into the same `spec.yaml`+`acceptance.yaml`. `--use-spec` is the
**pure machine seam**: what you write is what gets built, byte-for-byte.

**The weld / fit-test** — your engine is *done* on an output only when this is green:

```bash
tools/validate-spec.sh <name|specs-dir> --strict
# ✅ Contract OK — N features, M AC, K routes. Sẵn sàng `area run --use-spec`.
```

It calls the factory's own `validate_cross` directly, so passing it **is** fitting the
contract. Make it your engine's CI gate — this is AREA's spine applied to your half: *don't
let the reasoning that wrote the spec also certify it; let the factory's gate certify it.*

---

## 1 · Core principle — decouple shape from schema

The trap in "the spec engine's output must match the factory's input" is assuming
*many input shapes ⇒ many output schemas*. **Wrong.** The factory has exactly one internal
contract. A one-line idea and a 40-page PRD **emit the same schema** — they differ only in
**how much your engine had to infer**, and that difference has a home that is **not** the
schema:

| What varies with input richness | Where it goes | NOT where it goes |
|---|---|---|
| How much was inferred vs transcribed | `assumptions.yaml` (`material` flags) | ❌ the schema |
| Whether it's safe to build unattended | the `--clarify` stop threshold | ❌ the schema |
| Which user-given facts are non-negotiable | `--expect` ground-truth channel | ❌ paraphrased into prose |

Keep the output schema invariant; route the variance through those three channels (§5).

---

## 2 · The invariant output schema

Source of truth: [area/spec/models.py](../area/spec/models.py). Pydantic-validated.

### `spec.yaml`

```yaml
name: <str>                     # app / product name
summary: <str>                  # one or two sentences
stack: nextjs                   # default "nextjs"
entities:                       # [] allowed
  - name: <Entity>
    fields:
      - {name: <str>, type: <string|text|int|float|bool|datetime|enum>, required: <bool>}
features:                       # >= 1 required
  - id: <kebab-case>            # referenced by acceptance.criteria[].feature
    title: <str>
    description: <str>
routes:                         # every path the app SERVES; see §6 rule R2/R4
  - {path: "/boards/[id]", purpose: <str>, kind: <page|api|action>}   # path absolute
ui:                             # OPTIONAL; Flow-B capture fills it, you may hint
  description: <str>
  palette: [<color>, ...]
```

### `acceptance.yaml`  — **this is the oracle; treat it as the most important file**

```yaml
criteria:                       # >= 1; every feature.id must be covered
  - id: AC-1
    feature: <must match a spec.features[].id>
    given: <starting state>
    when: <user action — quote literal paths/values; see §6 R4>
    then: <observable, testable result>
    verify_by: <execution|inspection|demonstration|analysis>   # see §6 R5
```

`verify_by` values are `VERIFY_METHODS` in models.py:
- **execution** — run the system, observe the outcome. **Required for any runtime claim.**
- **inspection** — read source/config/manifest. OK for "route X does not exist"; never for a
  claim about what the *running* app does.
- **demonstration** — drive it live (browser, deployed instance).
- **analysis** — derive it (types, a proof, a measured budget).

### `assumptions.yaml`  — the confidence sidecar (optional file, but you should always write it)

```yaml
assumptions:
  - question: <what the request left unclear>
    assumption: <the default you chose>
    material: <true|false>      # true = a wrong guess here changes the app materially
```

Empty (`assumptions: []`) **only** when the request was genuinely unambiguous. `--use-spec`'s
verifier does not require this file, but the `--clarify` gate reads it (§5, §7).

---

## 3 · The fit-test — the rules `validate_cross` enforces

**Fatal** (output rejected; `validate-spec.sh` exits non-zero):

1. `spec.yaml` / `acceptance.yaml` missing, invalid YAML, or schema mismatch.
2. `spec.features` empty, or `acceptance.criteria` empty.
3. an `acceptance.criteria[].feature` that is not a `spec.features[].id` (**dangling ref**).
4. a `spec.features[].id` with **no** acceptance criterion (**uncovered feature**).
5. a `routes[].path` that is not absolute (must start with `/`).
6. criteria that **navigate** to a page while `spec.routes` is **empty** (the taskboard-clone
   trap — the oracle gets authored against invented URLs).

**Advisory** (clean by default; **fatal under `--strict`**):

7. a criterion that navigates without quoting any **declared** route
   (`routes_unquoted`) — the self-containment warning (§6 R4).

---

## 4 · Input → contract mapping

How each raw-input shape lands on the contract, what it typically omits, and how your engine
should adapt. **The output schema is the same in every row.**

| Input shape | Fills directly | Typically missing | Adapt strategy |
|---|---|---|---|
| **1-line idea** | `summary`, maybe 1 `feature` | entities, routes, AC, constraints | infer a minimal viable surface; mark **everything inferred `material: true`**; expect a clarify-stop |
| **User story + features** | `features[]`, some AC | entities, literal route paths, edge/error AC | expand each story into given/when/then; **add the error/edge cases** the user didn't write |
| **Full PRD** | features, entities, AC, constraints | `verify_by` method, literal-path phrasing | normalize to schema; assign `verify_by` honestly; quote paths |
| **Technical constraints only** | `stack`, entities, routes, NFR budget | **features + AC (the behavioral "what")** | **refuse / clarify** — constraints alone cannot yield an oracle (§7) |

The last row is the sharp one: **technical constraints alone are an insufficient input.** With
no expected behavior there is no oracle, so your engine must detect "constraints without
behavior" and stop rather than emit a confident spec.

---

## 5 · The three variance channels

**(a) `assumptions.yaml` with `material`** — the honest record of "I only had a 1-liner, so I
guessed X." The poorer the input, the denser this ledger. This is where input-shape variance
*lives* — not in the schema.

**(b) the `--clarify` stop threshold** — in `--clarify` mode (default ON), **any unanswered
`material: true` assumption STOPS the build at the spec** and asks the human
([area/spec/clarify.py](../area/spec/clarify.py) `open_questions`). Your engine should **mirror
this**: fail early and cheaply on your side so a thin input never reaches a funded build.

**(c) `--expect` / `--expect-file`** — concrete expected-result examples the user gave are
**authoritative ground truth**: the factory turns each into an acceptance criterion and must
not weaken, merge, or drop it ([area/spec/extract.py](../area/spec/extract.py) `expected_block`).
Whatever the input shape, **extract every concrete example and pass it through `--expect-file`
verbatim** — do not paraphrase. This is your main lever on oracle *strength*.

---

## 6 · Authoring rules (the gotchas that pass review)

- **R1 — coverage both ways.** Every `feature.id` has ≥1 AC; every `AC.feature` names a real
  feature. (Fatal rules 3–4.)
- **R2 — list every served path in `routes`**, absolute, pages first. (Fatal rules 5–6.)
- **R3 — don't invent scope.** Carry over only what the input states; put every gap in
  `assumptions.yaml`, don't silently paper over it with a feature.
- **R4 — `acceptance.yaml` must be self-contained.** The independent holdout author sees
  **only `acceptance.yaml`, never `spec.yaml`.** So any path/value a test needs must be written
  **literally** in `given/when/then` — "when they request `/boards/7`", not "when they open a
  board". An unnamed path gets invented and the frozen oracle asserts against a URL the app may
  not serve. (Advisory rule 7; `--strict` makes it fatal.)
- **R5 — `verify_by` must be honest.** Pick the weakest method that can actually settle the
  `then`; a runtime claim is `execution`. A criterion verified by the wrong method is worse
  than a missing one — it reports PASS for a property nobody checked (the `expenses` AC-14
  bug: a runtime "no network" claim "verified" by grepping source).

---

## 7 · Refuse / stop threshold

Do **not** emit a confident spec below the bar. Stop and clarify when:

- any **material** ambiguity is unresolved (mark it `material: true` and let the clarify gate
  stop — or stop on your side first), **or**
- the input is **technical constraints only** (no behavioral "what") — there is nothing to
  build an oracle from, **or**
- you cannot write a single concrete `then` for a feature — that feature is not yet buildable.

A clarify-stop is a success of the method, not a failure: it is the factory refusing to build
a guess. Cheaper to stop at the spec than to burn a build on an invented requirement.

---

## 8 · Worked example — one idea, two input granularities, same schema

**Input A (1-line idea):** *"a tiny link shortener."*

→ `spec.yaml`: `summary` set, 2 inferred features (`create`, `redirect`), inferred `Link`
entity and routes. → `assumptions.yaml`: **dense** — "code length? (assumed 6) [material]",
"persistence durable? (assumed yes) [material]", "allow duplicate URLs? (assumed yes)
[material]". → **clarify-stops** on the material ones.

**Input B (PRD excerpt):** states the routes (`POST /`, `GET /{code}`, `GET /`), the `Link`
entity, and 5 concrete expected results including the `/zzzzzz` → 404 and the empty-URL error.

→ **same `spec.yaml` schema**, but `assumptions.yaml` is nearly empty, the 5 examples become
AC-1…AC-5 via `--expect-file` (ground truth), and it **builds unattended** with no clarify-stop.

Identical schema; the delta is entirely in `assumptions.yaml` density and the clarify outcome.
That is the core principle (§1) made concrete.

---

## 9 · Integration checklist for the spec engine

- [ ] Emit `spec.yaml` + `acceptance.yaml` (+ `assumptions.yaml`) into `specs/<name>/`.
- [ ] Classify the input shape → set inference effort and `material` density (§4), **not** the
      schema.
- [ ] Extract every user-given concrete example → `--expect-file`, verbatim (§5c).
- [ ] Mark every inferred decision honestly in `assumptions.yaml` (§5a).
- [ ] Run `tools/validate-spec.sh <name> --strict` in CI; green is the definition of done (§0).
- [ ] Below threshold (§7) → clarify, don't ship a confident spec.
- [ ] Hand off via `area run --name <name> --use-spec` (or `area intake`).
