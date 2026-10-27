# Examples — apps AREA actually built

Real applications the factory produced from a requirement, committed with their
**spec + independent locked oracle + generated source + gate evidence**. This is
the visible proof of what AREA does — and you can run them **without a Claude key
or any cost**.

| Example | What it shows | Evidence |
|---------|---------------|----------|
| [`taskboard/`](taskboard/) | multi-page **auth** app: signup/login (hashed), per-user isolation, boards + tasks, durable sqlite | 18/18 locked holdout · all 7 gates green · e2e on a real browser · $5.19 |

Run one with no LLM key:

```bash
area demo taskboard      # install → build → serve → open browser
```

Each example's own README walks through the oracle-loop: requirement → spec →
**locked holdout (the independent oracle)** → build-to-green → gates → provenance.
To build your *own* app, see the [top-level README](../README.md).
