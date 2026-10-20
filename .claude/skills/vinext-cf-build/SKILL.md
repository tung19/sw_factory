---
name: vinext-cf-build
description: Get a green Cloudflare (vinext) build that also passes `npm audit`, and keep node:sqlite out of the Workers bundle. Use when building, auditing, or deploying an AREA app to Cloudflare Workers — target "cloudflare", a `build:cf` / `vite build` script, a D1 database, or an `npm audit` gate failing on braces.
---

# Cloudflare (vinext) build — the known gotchas + fixes

AREA's Cloudflare target uses **vinext** (Vite-based: `build:cf` = `vite build`,
NOT `next build`; it shims `next/*`). These issues recur on every vinext app.

## 1. compatibility_date vs workerd
`vinext init` writes `compatibilityDate` = today, but the bundled `workerd` can be
a few days behind, and a future date **fails `vite build`**. Fix: set
`compatibilityDate` in `cloudflare.config.ts` to the installed workerd's release
date or earlier — check `npm ls workerd`. Keep `compatibilityFlags:
["nodejs_compat"]`.

## 2. Fastest green build: clone a known-good sibling (don't run `vinext init`)
Copy from a sibling app that already builds (e.g. `apps/gb_d1` for the D1 variant):
`package.json`, `package-lock.json`, `node_modules`, `tsconfig.json`,
`next.config.ts`, `vite.config.ts`, `next-env.d.ts`, `cloudflare.config.ts`.
Change only `name` in package.json and the worker `name` in cloudflare.config.ts.
This pins the exact workerd the lockfile pairs with, so the compat-date is already
correct. Scripts the verifier calls: `"test":"vitest run"`, `"build:cf":"vite
build"`, `"deploy":"vinext-cloudflare deploy"`.

## 3. `npm audit` gate fails on braces (unpatched HIGH CVE)
`npm audit --audit-level=high` hard-fails for every vinext app via build tooling
(vinext → vite-plugin-commonjs → … → micromatch → **braces**, no published patch).
Do NOT `npm audit fix --force` (it force-downgrades vinext and breaks build:cf).
App-level fix that keeps the strict gate untouched:
1. `"overrides": {"fflate": "^0.7.5"}` (clears the satori/@vercel/og chain).
2. Vendor braces into `vendor/braces` (copy of 3.0.3) + a real CVE patch: a
   nesting-depth guard in `lib/parse.js` (`maxDepth` default 256, throw
   SyntaxError before the deep recursive walk overflows). Then
   `"overrides": {"braces": "file:./vendor/braces"}`. npm skips `file:` deps in
   audit, so the chain clears → 0 vulns.

## 4. `file:` braces prunes `fill-range` → "Cannot find module 'fill-range'"
`node_modules/braces` becomes a symlink to `vendor/braces`, and **any** later
`npm i` re-hoists and prunes braces' transitive dep `fill-range`, breaking
`npm run dev` / `build:cf`. Make the vendored package self-contained:
`cd vendor/braces && npm install --omit=dev` (installs fill-range + is-number +
to-regex-range into `vendor/braces/node_modules`). Run this right after any
`npm i` in these apps.

## 5. Keep node:sqlite OUT of the Workers bundle (D1 apps)
The holdout tests drive a durable store via `node:sqlite`, but that must never
enter the Cloudflare build. Split the seam:
- `lib/schema.ts` — platform-free: the `Db` interface (`run/get/all/close?`) +
  `migrate(db)` (one `CREATE TABLE IF NOT EXISTS` per `db.run`, works on both
  engines). Imports nothing platform-specific.
- `lib/db.ts` — wraps `node:sqlite` (`DatabaseSync`), TEST-ONLY; re-exports
  `migrate` from schema. `createDb()` = `:memory:`, `createDb(path)` = durable.
- `lib/d1.ts` — wraps the D1 binding (`prepare().bind().run()/first()/all()`,
  `meta.last_row_id`), APP-ONLY.
- Domain modules (`lib/auth`, `lib/notes`) import only the `Db` TYPE → zero
  platform deps. App imports `migrate` from `lib/schema`, never `lib/db`.
- Verify exclusion: `grep -rl "node:sqlite\|DatabaseSync\|createSqliteDb"
  .cloudflare/output --include="*.js"` must be empty.

## 6. Auth that runs in BOTH vitest-node and workerd
Use **Web Crypto only** (no node:crypto, no deps): PBKDF2 via `crypto.subtle` +
`crypto.getRandomValues`, stored as `pbkdf2$<iters>$<saltHex>$<hashHex>`. Session
= stateless signed cookie `<userId>.<HMAC-SHA256(userId)>`. Wrap cookie reads in
try/catch so a build-time render probe (no request scope) falls back to
logged-out. For signup/login UI use **two dedicated server actions**
(`signupAction` / `loginAction`) bound to separate `<form>`s — NOT one action
reading an `intent` field (that intent reaches formData unreliably and breaks
signup live).
