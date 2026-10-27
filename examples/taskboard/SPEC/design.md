# taskboard — system design

Multi-page team task board (Next.js App Router, Node runtime). Users sign up / log in,
then manage their own private boards and tasks. Strict per-user isolation, hashed
passwords, durable persistence across restarts.

**App root** (all file-plan paths are relative to it): `workspace/apps/taskboard/`
**Runtime:** Next.js 14/15 App Router, `runtime = 'nodejs'` on every route/action that
touches the DB (SQLite needs Node, not Edge).

---

## 1 · Components & responsibilities

| Component | Responsibility |
|---|---|
| **DB layer** (`lib/db.ts`) | One process-wide `better-sqlite3` connection to a file; `initSchema()` (idempotent `CREATE TABLE IF NOT EXISTS`) runs once at import. Durable file store → survives restart. |
| **Repositories** (`lib/repo.ts`) | All SQL, *always* owner-scoped. `createUser / findUserByEmail / findUserById`; `createBoard(ownerId,…) / listBoards(ownerId) / getBoardForOwner(id,ownerId)`; `addTask / listTasks(boardId) / setTaskStatus`. Isolation is enforced *here* — every board/task read requires the ownerId to match. |
| **Password hashing** (`lib/password.ts`) | `hashPassword` / `verifyPassword` via Node `crypto.scrypt` + random salt, stored as `scrypt$<salt>$<hash>`. Zero extra deps, never stores plaintext. |
| **Session** (`lib/session.ts`) | Stateless HMAC-signed cookie (`sid`) carrying `userId`. `createSession(userId)` sets an httpOnly/sameSite=lax/secure cookie; `getSessionUser()` verifies the signature and returns the user (or null); `destroySession()` clears it. Secret from `SESSION_SECRET` env (dev fallback constant). |
| **Auth guard** (`lib/auth.ts`) | `requireUser()` → `getSessionUser()` or `redirect('/login')`. Used by protected pages and every mutating action. |
| **Validation** (`lib/validation.ts`) | Trim/normalize email, non-empty password/board-name/task-title, `status ∈ {todo,doing,done}`. Reject (throw) rather than coerce. |
| **Pages (Server Components)** | Render login/signup, boards-list, board-detail; call repos read-side. |
| **Server Actions** | All writes + auth transitions; see §3. |

Data flow: Page/Action → `requireUser()` → repo (owner-scoped) → DB file.

---

## 2 · Data model (SQLite)

```sql
users (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  email        TEXT    NOT NULL UNIQUE COLLATE NOCASE,
  passwordHash TEXT    NOT NULL,
  createdAt    TEXT    NOT NULL DEFAULT (datetime('now'))
);

boards (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  name      TEXT    NOT NULL,
  ownerId   INTEGER NOT NULL REFERENCES users(id),
  createdAt TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_boards_owner ON boards(ownerId);

tasks (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  boardId   INTEGER NOT NULL REFERENCES boards(id),
  title     TEXT    NOT NULL,
  status    TEXT    NOT NULL CHECK (status IN ('todo','doing','done')),
  createdAt TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_tasks_board ON tasks(boardId);
```

- **Isolation invariant:** a task is reachable only via a board whose `ownerId` =
  current user. Every task query joins/filters through `getBoardForOwner`, so there is
  no code path that returns another user's data (covers AC-11).
- DB file path from `DB_PATH` env, default `data/taskboard.db` (gitignored); created on
  first run. File-backed = durable (AC-12).

---

## 3 · Routes / pages & Server Actions

**Pages**
| Path | Access | Contents |
|---|---|---|
| `/login` | public | Combined login **and** signup forms (two `<form action={…}>`). Shows error via `?error=` search param. Also the post-logout / redirect-on-guard target. |
| `/` | public | Redirects: logged-in → `/boards`, else → `/login`. |
| `/boards` | **guarded** | `requireUser()`, then `listBoards(user.id)`; create-board form + list of the user's boards (each links to `/boards/[id]`). |
| `/boards/[id]` | **guarded** | `requireUser()`, `getBoardForOwner(id, user.id)` → `notFound()`/redirect if not owned; lists tasks; add-task form; per-task status control. |

**Server Actions** (`app/actions.ts`, all `'use server'`)
| Action | Does | AC |
|---|---|---|
| `signup(formData)` | validate → reject if email exists → `hashPassword` → `createUser` → `createSession` → `redirect('/boards')` | AC-1, AC-4 |
| `login(formData)` | `findUserByEmail` → `verifyPassword`; on fail `redirect('/login?error=invalid')` (no cookie set); on success `createSession` → `redirect('/boards')` | AC-2, AC-3 |
| `logout()` | `destroySession` → `redirect('/login')` | — |
| `createBoard(formData)` | `requireUser` → validate name → `createBoard(user.id,name)` → `revalidatePath('/boards')` | AC-6 |
| `addTask(formData)` | `requireUser` → `getBoardForOwner` (deny if not owner) → validate title+status → `addTask` → `revalidatePath('/boards/[id]')` | AC-9, AC-11 |
| `changeTaskStatus(formData)` | `requireUser` → verify task's board is owner's → `setTaskStatus` → revalidate | AC-10, AC-11 |

Guard behavior (AC-5): any protected page/action with no valid session → `redirect('/login')`.

---

## 4 · File plan (exact paths to create)

```
package.json                      # deps: next, react, react-dom, better-sqlite3; types
next.config.mjs                   # serverExternalPackages: ['better-sqlite3']
tsconfig.json
.gitignore                        # /data, node_modules, .next
.env.example                      # SESSION_SECRET, DB_PATH

lib/db.ts                         # connection + initSchema()
lib/repo.ts                       # owner-scoped queries (users/boards/tasks)
lib/password.ts                   # scrypt hash/verify
lib/session.ts                    # signed-cookie session create/get/destroy
lib/auth.ts                       # requireUser()
lib/validation.ts                 # input validation + status enum guard
lib/types.ts                      # User/Board/Task/Status types

app/layout.tsx                    # root layout
app/page.tsx                      # redirect / → /boards or /login
app/actions.ts                    # all server actions (§3)
app/login/page.tsx                # combined login + signup forms
app/boards/page.tsx               # boards-list (guarded) + create-board form
app/boards/[id]/page.tsx          # board-detail (guarded): tasks + add + status controls
app/boards/[id]/TaskStatusControl.tsx  # client/form wrapper for changeTaskStatus
app/globals.css                   # minimal styling
```

Holdout oracle (authored separately, not by this stage): `__tests__/_holdout/`.

---

## 5 · Key decisions & risks

**Decisions**
- **better-sqlite3 (file-backed)** for durable persistence — synchronous, simplest
  correct store for a single-node Next.js app; the file survives restart (AC-12). Mark
  it `serverExternalPackages` so Next doesn't bundle the native module. (If native build
  is a problem, swap to built-in `node:sqlite` behind the same `lib/db` interface.)
- **scrypt via `node:crypto`** — no bcrypt native dep, salted, plaintext never stored.
- **Stateless signed cookie** session — no session table needed; httpOnly + sameSite=lax
  + signed with `SESSION_SECRET`. Survives restart as long as the secret is stable.
- **Isolation at the repo layer** — there is literally no query that fetches a board/task
  without an ownerId filter, so AC-11 holds structurally, not just by UI hiding.
- **Server Actions + `revalidatePath`** over API routes — fewer files, server-side auth.

**Risks / mitigations**
- *Dev HMR resets module state* → keep the DB connection on `globalThis` singleton so
  schema init and the file handle aren't duplicated across hot reloads.
- *`SESSION_SECRET` unset* → required in prod; dev fallback constant (document in
  `.env.example`). Rotating it logs everyone out (acceptable).
- *Node vs Edge runtime* → force `export const runtime = 'nodejs'`; SQLite + crypto are
  not Edge-safe.
- *IDOR on `/boards/[id]` and task actions* → always go through `getBoardForOwner`;
  not-owned → `notFound()` (don't leak existence).
- *Concurrent writes* → better-sqlite3 is synchronous/serialized in-process; enable WAL
  for read concurrency.
- *Email case/dupes* → `UNIQUE COLLATE NOCASE` + normalize on input.
```
