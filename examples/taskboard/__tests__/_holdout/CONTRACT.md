# Holdout contract — module surface the implementation must satisfy

These locked holdout tests import the app through stable public modules only. The
implementation must expose exactly the paths, exports, and shapes below. All functions
are **async** (return Promises). Tests resolve modules via extensionless imports, so
each may be `.ts`, `.js`, or `.mjs`.

## Environment / test harness contract

- `process.env.TASKBOARD_DB` — absolute path to the **durable store file** the app uses.
  The tests set this before importing the modules; the implementation MUST read it to
  locate its persistent store. Each test file uses a unique path.
- The store must be durable: re-importing the modules in a fresh module registry
  (simulating a server restart) must still read previously written data (see AC-12).
- Auth checks run **before** resource lookup: an unauthenticated page request returns a
  login redirect regardless of whether the requested board exists.

## `lib/routes`

```
export const routes: {
  login: string          // path of the login / signup page
  boardsList: string     // path of the boards-list page
  board(boardId: string): string  // path of a board-detail page (not asserted directly)
}
```
`routes.login` and `routes.boardsList` are distinct non-empty path strings.

## `lib/auth`

```
signUp(email: string, password: string):
  Promise<{ token: string, user: { id: string, email: string }, redirectTo: string }>
  // Creates an account + logged-in session. redirectTo === routes.boardsList.
  // Rejects (throws) if an account already exists for the email.

logIn(email: string, password: string):
  Promise<{ token: string, user: { id: string, email: string }, redirectTo: string }>
  // On success: redirectTo === routes.boardsList.
  // Rejects (throws) on unknown email or wrong password — no session is returned.

requireAuth(token: string | undefined):
  Promise<{ ok: true, user: { id: string, email: string } }
         | { ok: false, redirectTo: string }>  // redirectTo === routes.login when invalid/missing
```

## `lib/boards`

```
loadBoardsPage(token: string | undefined):
  Promise<{ redirectTo: string }                                   // unauthenticated → routes.login
         | { user: { id, email }, boards: Array<Board> }>          // authenticated: only this user's boards

createBoard(token: string, name: string):
  Promise<{ board: Board }>   // persisted, owned by the session user

loadBoardPage(token: string | undefined, boardId: string):
  Promise<{ redirectTo: string }                 // unauthenticated → routes.login
         | { board: Board, tasks: Array<Task> }>  // owner only
  // Rejects (throws) when an authenticated user is NOT the owner of the board.

// Board = { id: string, name: string, ownerId: string }
```

## `lib/tasks`

```
addTask(token: string, boardId: string, input: { title: string, status: Status }):
  Promise<{ task: Task }>
  // Persists a task on the owned board. Rejects on a non-owner, or an invalid status.

setTaskStatus(token: string, boardId: string, taskId: string, status: Status):
  Promise<{ task: Task }>
  // Updates + persists the task's status. Rejects on a non-owner, or an invalid status.

// Status = 'todo' | 'doing' | 'done'
// Task   = { id: string, boardId: string, title: string, status: Status }
```

## `lib/db`

```
getAccountByEmail(email: string):
  Promise<{ id: string, email: string, passwordHash: string } | null>
  // Reads the stored account record back from the persistent store.
  // passwordHash is the stored credential — a hash, never the plaintext.
```
