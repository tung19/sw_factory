import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'
import type { DatabaseSync as DatabaseSyncType } from 'node:sqlite'
import type { Account, Board, Task, Status } from './types'

// Load node:sqlite via a runtime require so neither Vite (vitest) nor webpack (next
// build) tries to statically bundle this Node builtin — both mis-resolve the
// `node:sqlite` specifier. `import type` above is erased, so it carries no runtime cost.
const nodeRequire = createRequire(import.meta.url)
const { DatabaseSync } = nodeRequire('node:sqlite') as typeof import('node:sqlite')
type DatabaseSync = DatabaseSyncType

// Durable, file-backed store using Node's built-in SQLite. The file path comes from
// TASKBOARD_DB (the holdout sets this before importing); otherwise ./data/taskboard.db.
// Because the data lives in a file, a fresh module registry (simulated restart) reads
// back previously-committed rows — satisfying AC-12.

const SCHEMA = `
CREATE TABLE IF NOT EXISTS users (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  email        TEXT    NOT NULL UNIQUE COLLATE NOCASE,
  passwordHash TEXT    NOT NULL,
  createdAt    TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS boards (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  name      TEXT    NOT NULL,
  ownerId   INTEGER NOT NULL,
  createdAt TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_boards_owner ON boards(ownerId);
CREATE TABLE IF NOT EXISTS tasks (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  boardId   INTEGER NOT NULL,
  title     TEXT    NOT NULL,
  status    TEXT    NOT NULL CHECK (status IN ('todo','doing','done')),
  createdAt TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_tasks_board ON tasks(boardId);
`

function resolveDbPath(): string {
  const p = process.env.TASKBOARD_DB
  if (p && p.trim()) return p.trim()
  return path.join(process.cwd(), 'data', 'taskboard.db')
}

// Cache connections by file path on globalThis so Next's dev HMR (and repeated imports)
// reuse one handle per store file instead of leaking connections.
function getDb(): DatabaseSync {
  const file = resolveDbPath()
  const g = globalThis as unknown as { __taskboardDbs?: Map<string, DatabaseSync> }
  if (!g.__taskboardDbs) g.__taskboardDbs = new Map()
  let db = g.__taskboardDbs.get(file)
  if (!db) {
    if (file !== ':memory:') fs.mkdirSync(path.dirname(file), { recursive: true })
    db = new DatabaseSync(file)
    db.exec(SCHEMA)
    g.__taskboardDbs.set(file, db)
  }
  return db
}

function toInt(id: string): number | null {
  const n = Number(id)
  return Number.isFinite(n) ? n : null
}

// ---- accounts ----

function rowToAccount(r: any): Account | null {
  if (!r) return null
  return { id: String(r.id), email: String(r.email), passwordHash: String(r.passwordHash) }
}

export async function getAccountByEmail(email: string): Promise<Account | null> {
  const r = getDb()
    .prepare('SELECT id, email, passwordHash FROM users WHERE email = ? COLLATE NOCASE')
    .get(email)
  return rowToAccount(r)
}

export function getAccountById(id: string): Account | null {
  const n = toInt(id)
  if (n === null) return null
  const r = getDb().prepare('SELECT id, email, passwordHash FROM users WHERE id = ?').get(n)
  return rowToAccount(r)
}

export function createAccount(email: string, passwordHash: string): Account {
  const info = getDb()
    .prepare('INSERT INTO users (email, passwordHash) VALUES (?, ?)')
    .run(email, passwordHash)
  return { id: String(info.lastInsertRowid), email, passwordHash }
}

// ---- boards ----

function rowToBoard(r: any): Board {
  return { id: String(r.id), name: String(r.name), ownerId: String(r.ownerId) }
}

export function insertBoard(ownerId: string, name: string): Board {
  const info = getDb()
    .prepare('INSERT INTO boards (name, ownerId) VALUES (?, ?)')
    .run(name, Number(ownerId))
  return { id: String(info.lastInsertRowid), name, ownerId: String(ownerId) }
}

export function listBoardsByOwner(ownerId: string): Board[] {
  const rows = getDb()
    .prepare('SELECT id, name, ownerId FROM boards WHERE ownerId = ? ORDER BY id')
    .all(Number(ownerId)) as any[]
  return rows.map(rowToBoard)
}

export function getBoardById(id: string): Board | null {
  const n = toInt(id)
  if (n === null) return null
  const r = getDb().prepare('SELECT id, name, ownerId FROM boards WHERE id = ?').get(n)
  return r ? rowToBoard(r) : null
}

// ---- tasks ----

function rowToTask(r: any): Task {
  return {
    id: String(r.id),
    boardId: String(r.boardId),
    title: String(r.title),
    status: r.status as Status,
  }
}

export function insertTask(boardId: string, title: string, status: Status): Task {
  const info = getDb()
    .prepare('INSERT INTO tasks (boardId, title, status) VALUES (?, ?, ?)')
    .run(Number(boardId), title, status)
  return { id: String(info.lastInsertRowid), boardId: String(boardId), title, status }
}

export function listTasksByBoard(boardId: string): Task[] {
  const rows = getDb()
    .prepare('SELECT id, boardId, title, status FROM tasks WHERE boardId = ? ORDER BY id')
    .all(Number(boardId)) as any[]
  return rows.map(rowToTask)
}

export function getTaskById(id: string): Task | null {
  const n = toInt(id)
  if (n === null) return null
  const r = getDb().prepare('SELECT id, boardId, title, status FROM tasks WHERE id = ?').get(n)
  return r ? rowToTask(r) : null
}

export function updateTaskStatus(id: string, status: Status): Task | null {
  const n = toInt(id)
  if (n === null) return null
  getDb().prepare('UPDATE tasks SET status = ? WHERE id = ?').run(status, n)
  return getTaskById(id)
}
