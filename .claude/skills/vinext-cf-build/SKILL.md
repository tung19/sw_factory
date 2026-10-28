---
name: vinext-cf-build
# Only reaches a build for these targets: `area.skills.install_skills` does not
# copy it into a plain/vercel app, and `area.profile` folds it into the version of
# the kinds that INSTALL it rather than every kind that merely runs in an app dir.
targets: [cloudflare]
description: Get a green Cloudflare (vinext) build that also passes `npm audit`, and keep node:sqlite out of the Workers bundle. Use when building, auditing, or deploying an AREA app to Cloudflare Workers — target "cloudflare", a `build:cf` / `vite build` script, a D1 database, or an `npm audit` gate failing on braces.
---

# Cloudflare (vinext) build — the known gotchas + fixes

AREA's Cloudflare target uses **vinext** (Vite-based: `build:cf` = `vite build`,
NOT `next build`; it shims `next/*`). These issues recur on every vinext app.

> **AREA now automates §1–§4 deterministically** (`area/build/cf_scaffold.py`, PR2):
> - `area cf-fix <app>` — pins the compat date to the installed workerd (§1), writes
>   the braces/fflate overrides, and vendors the patched braces (§3). `harden_cf_app`
>   runs in the Cloudflare deploy path as a fail-open safety net.
> - `area cf-clone <app> --from <sibling>` — clones a known-good toolchain (§2).
> - `restore_vendored_braces` re-seeds the vendored braces after a prune (§4), offline.
>
> The notes below are the underlying mechanism (and what to do for the bits AREA
> does NOT automate — bootstrapping the first sibling, the version-specific vite
> bump). Verified live on **vinext 1.3.0 / Next 16.4 / workerd 1.20261019** (Oct 2026).

## 1. compatibility_date vs workerd
`vinext init` writes `compatibilityDate` = today, but the bundled `workerd` can be
a few days behind, and a future date **fails `vite build`**. workerd versions ARE
dates (`1.YYYYMMDD.N`), so the correct compat date is deterministic:
`area cf-fix` reads `npm ls workerd` and rewrites `compatibilityDate` in
`cloudflare.config.ts` to the workerd date (e.g. observed `2026-10-22` today →
pinned to `2026-10-19`). Keep `compatibilityFlags: ["nodejs_compat"]`.

By hand, if the `area` CLI is not on your PATH (it is not guaranteed to be inside a
generated app): run `npm ls workerd`, read the date out of its `1.YYYYMMDD.N` version,
and set `compatibilityDate` in `cloudflare.config.ts` to that date or earlier.

## 2. Fastest green build: clone a known-good sibling (don't run `vinext init`)
`area cf-clone <app> --from <sibling>` copies a sibling that already builds green:
`package.json`, `package-lock.json`, `node_modules`, `vendor/`, `tsconfig.json`,
`next.config.ts`, `vite.config.ts`, `next-env.d.ts`, `cloudflare.config.ts`, then
rewrites `name` in package.json + the worker `name` in cloudflare.config.ts. This
pins the exact workerd the lockfile pairs with, so the compat-date is already
correct. Scripts the verifier calls: `"test":"vitest run"`, `"build:cf":"vite
build"`, `"deploy":"vinext-cloudflare deploy"`.

**Bootstrapping the FIRST sibling** (no sibling to clone yet) — `vinext init` is a
MIGRATE command (not a scaffolder), and it's fully non-interactive only with every
choice flagged. The verified recipe:
```
npx create-next-app@latest app --ts --app --no-src-dir --no-tailwind --no-eslint --yes
cd app
npx vinext@latest init --platform=cloudflare --cdn-cache=static-assets --data-cache=none --image-optimization=none
area cf-fix app            # pin compat date + vendor braces + overrides
# bump the direct vite dep to the npm-audit-recommended patch (see §3)
npm install && (cd vendor/braces && npm install --omit=dev)   # or `area cf-fix` re-vendor
npm run build:vinext       # ✓ built — this app is now a known-good sibling
```
Note: vinext 1.3.0 names the scripts `build:vinext`/`deploy:vinext` (AREA's gate
expects `build:cf` — alias it in package.json: `"build:cf": "vite build"`).

## 3. `npm audit` gate fails HIGH (braces + fflate + vite)
On vinext 1.3.0 a fresh app shows **7 HIGH** (measured). They fall in three groups;
`area cf-fix` handles the first two deterministically, the third is version-specific:
1. **braces** (5 of 7: `braces → micromatch → fast-glob → vite-plugin-dynamic-import
   → vite-plugin-commonjs → vinext`) — braces' deeply-nested **stack-exhaustion**
   CVE. Fix: vendor a patched braces (3.0.3 + a `maxDepth` guard, default 256, that
   throws `SyntaxError` before the deep walk) at `vendor/braces` + override
   `"braces": "file:./vendor/braces"`. npm skips `file:` deps in audit → the whole
   chain clears. `area cf-fix` vendors this from `area/build/templates/braces`.
2. **@vercel/og chain** — `"overrides": {"fflate": "^0.7.5"}`. (`area cf-fix` writes it.)
3. **vite** (launch-editor command-execution) — vite is a **direct devDependency**,
   so npm rejects an `overrides` entry for it (`EOVERRIDE conflicts with direct
   dependency`). Bump the direct dep instead: set `devDependencies.vite` to the
   `npm audit fix` patch (observed `8.3.0 → 8.3.5`). This is **version-specific** —
   AREA does NOT hardcode it; re-check per vinext release. Do NOT `npm audit fix
   --force` (it force-downgrades vinext + removes the vendored braces).

Result after all three: **0 vulns** (verified live).

## 4. a parent `npm install` prunes the vendored braces' `fill-range`
After `braces: file:./vendor/braces`, **any** later `npm i` re-hoists and prunes
braces' transitive deps (`fill-range` → "Cannot find module 'fill-range'", breaking
`build:cf`). AREA ships the deps under `vendor/braces/_deps/` (a `node_modules/`
name would be swallowed by .gitignore) and materialises them into `node_modules/`;
`restore_vendored_braces(app)` re-copies `_deps → node_modules` **offline** whenever
the prune happens (equivalent to the manual `cd vendor/braces && npm install
--omit=dev`, but with no network). Run it right after any `npm i`.

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
