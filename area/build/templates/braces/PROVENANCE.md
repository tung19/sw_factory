# Vendored braces (patched) — provenance

Vendored by AREA to clear the **HIGH** `npm audit` finding that every vinext
Cloudflare app hits: *braces vulnerable to stack-exhaustion denial of service
through deeply nested patterns*. See `.claude/skills/vinext-cf-build` §3.

- **braces 3.0.3** (MIT, `LICENSE`) — upstream source, unmodified except the patch below.
- **Patch** (`lib/parse.js`): a nesting-depth guard — `const maxDepth = … 256` and,
  after each `depth++`, `if (depth > maxDepth) throw new SyntaxError(…)`. This bounds
  the recursive walk so a deeply-nested pattern throws instead of exhausting memory.
  Both edits are tagged `// AREA CVE guard`.
- **`_deps/`** — braces' own transitive deps (`fill-range` 7.1.1, `is-number` 7.0.0,
  `to-regex-range` 5.0.1, all MIT), stored under `_deps/` rather than `node_modules/`
  because the repo `.gitignore` swallows `node_modules/`. `vendor_braces` /
  `restore_vendored_braces` materialise them into `node_modules/` in the target app.

Regenerate: `npm pack braces@3.0.3 fill-range@7.1.1 is-number@7.0.0 to-regex-range@5.0.1`,
extract, re-apply the two `// AREA CVE guard` edits, move deps under `_deps/`.
