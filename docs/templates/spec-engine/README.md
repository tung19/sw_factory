# Spec-engine fill-in templates

Drop-in templates + one worked example for the artifact your spec engine must emit so
**SW_Factory** can build autonomously. The full contract is
[../../spec-engine-contract.md](../../spec-engine-contract.md); this folder is the
"here, just fill these in" version.

## The one rule that surprises people

Your pipeline has stages — **User Story → BA Requirement → Function Spec Design**. The
factory has **one** input schema. Those stages are *your* internal pipeline; the factory
never sees them. They all pour into the **same** two files. Input richness changes **how
much you infer** (recorded in `assumptions.yaml`), **never the schema**.

```
        YOUR spec engine (any number of stages)                 THE FACTORY
  ┌───────────────┬────────────────┬──────────────────┐   ┌───────────────────────┐
  │  User Story   │ BA Requirement │  Function Spec    │ → │ spec.yaml              │
  │  [US]         │ [BA]           │  [FS]             │   │ acceptance.yaml (ORACLE)│
  └───────────────┴────────────────┴──────────────────┘   │ assumptions.yaml       │
                        one invariant artifact ───────────▶└───────────────────────┘
                                                            tools/validate-spec.sh = weld
```

## Which stage fills which field

| Field | Stage | Notes |
|---|---|---|
| `spec.summary`, `features[].id` / `title` | **[US]** User Story | one feature id per story |
| `spec.entities[]`, `spec.routes[]` | **[BA]** BA Requirement | the data model + every path served; NFR/constraints go to `assumptions.yaml`, not prose |
| `features[].description` (precise) | **[FS]** Function Spec | observable behaviour |
| **`acceptance.yaml` (all criteria)** | **[FS]** Function Spec | **the real work** — one criterion per functional requirement, plus the error/edge cases the story never wrote |
| `assumptions.yaml` | every stage | anything you had to infer; flag `material: true` if a wrong guess changes the app |

## Quality comes from the oracle, not the schema

`acceptance.yaml` is the oracle the build runs to green. **Quality ≤ strength +
INDEPENDENCE of the oracle.** The schema is easy to satisfy; a *strong* oracle is the job.
Six things decide whether the factory builds the right thing:

1. **Coverage both ways** — every feature has ≥1 AC; every AC names a real feature. *(fatal)*
2. **List every route**, absolute, pages first. *(fatal if an AC navigates and `routes` is empty)*
3. **Self-contained ACs** — the holdout author sees **only `acceptance.yaml`**. Quote every
   path/value **literally** in given/when/then. *(advisory; `--strict` makes it fatal)*
4. **Honest `verify_by`** — weakest method that truly settles `then`; a runtime claim is
   `execution`. *(the `expenses` AC-14 bug: a "no network" runtime claim "verified" by grep)*
5. **Concrete user examples → pass verbatim** via `--expect-file` (don't paraphrase).
6. **Error/edge cases** — empty input, over-limit, 404, duplicate, unauthorized.

## Use it

```bash
# 1. copy the templates for a new app
cp spec.template.yaml        /path/to/specs/<name>/spec.yaml
cp acceptance.template.yaml  /path/to/specs/<name>/acceptance.yaml
cp assumptions.template.yaml /path/to/specs/<name>/assumptions.yaml
#    …fill them in…

# 2. the weld — green == done (make it your spec engine's CI gate)
tools/validate-spec.sh /path/to/specs/<name> --strict

# 3. hand off to the factory
area run --name <name> --use-spec
```

## Worked example — `example-timeoff/`

A one-sentence user story ("employee requests time off against a leave balance") carried
through all three stages into a filled, **green** artifact:

```
$ tools/validate-spec.sh docs/templates/spec-engine/example-timeoff --strict
✅ Contract OK — 7 features, 9 AC, 2 routes. Sẵn sàng `area run --use-spec`.
```

Read it next to the templates. Note how `assumptions.yaml` carries the three **material**
inferences (starting balance, day-count rule, no approval workflow) — in `--clarify` mode
those *stop the build and ask you*, which is the factory refusing to build a guess.

> Contrast: `examples/taskboard/SPEC/` predates the `routes` field, so its criteria
> navigate with no paths declared — run the validator on it and it is **rejected**. That is
> the gate doing its job, not a bug.
