// CHAOS — adversarial / fuzz inputs.
//
// Asserts the domain degrades GRACEFULLY under hostile input: malformed values are
// rejected with a clean thrown Error (never an unexpected crash) and the durable store
// is left untouched, while legitimate-but-nasty content (unicode, control chars, NUL
// bytes, injection-shaped strings) round-trips through the SQLite store byte-for-byte
// and can never alter the schema (parameterized queries).
//
// Control/NUL bytes are assembled with String.fromCharCode so the literals survive the
// write channel intact rather than being mangled as source escapes.
import { describe, it, expect, beforeAll } from 'vitest'
import os from 'node:os'
import path from 'node:path'
import crypto from 'node:crypto'

let auth: any
let boards: any
let tasks: any
let db: any

beforeAll(async () => {
  process.env.TASKBOARD_DB = path.join(os.tmpdir(), `taskboard-chaos-fuzz-${crypto.randomUUID()}.db`)
  auth = await import('../../lib/auth')
  boards = await import('../../lib/boards')
  tasks = await import('../../lib/tasks')
  db = await import('../../lib/db')
})

function uid() {
  return crypto.randomUUID()
}

async function freshUser() {
  const { token, user } = await auth.signUp(`fuzz-${uid()}@example.com`, `Pw-${uid()}`)
  return { token, user }
}

async function freshBoard(token: string) {
  return (await boards.createBoard(token, `Board-${uid()}`)).board
}

// Control characters (incl. NUL, BEL, BS, TAB, LF, CR, ESC, US) sandwiched between
// non-whitespace guards so the stored value equals the input (the layer trims edges).
const CTRL = 'A' + String.fromCharCode(0, 1, 7, 8, 9, 10, 13, 27, 31) + 'Z'
const NUL = 'before' + String.fromCharCode(0) + 'after'

// Legitimate-but-nasty payloads that MUST be accepted and stored verbatim. None has
// leading/trailing whitespace, so trimming leaves them unchanged.
const ROUND_TRIP: Array<[string, string]> = [
  ['emoji+unicode', '🚀✅🧪 café — 日本語 Ωmega ∑'],
  ['control-chars', CTRL],
  ['nul-byte', NUL],
  ['sql-injection', "'); DROP TABLE tasks;--"],
  ['html-xss', '<script>alert(String.fromCharCode(88))</script>'],
  ['js-injection', '${process.exit(1)}`rm -rf /`'],
  ['long-within-limit', 'x'.repeat(9000)],
  ['json-ish', '{"id":1,"__proto__":{"admin":true}}'],
]

// Values that MUST be rejected cleanly (thrown Error) and persist nothing.
const REJECT_TITLES: Array<[string, unknown]> = [
  ['empty', ''],
  ['whitespace-only', '   \t\n  '],
  ['null', null],
  ['undefined', undefined],
  ['number', 123],
  ['boolean', true],
  ['object', { toString: () => 'evil' }],
  ['array', ['a', 'b']],
  ['too-long', 'x'.repeat(10001)],
]

describe('fuzz — task title round-trips hostile-but-valid content verbatim', () => {
  it.each(ROUND_TRIP)('stores and reads back %s unchanged', async (_label, title) => {
    const { token } = await freshUser()
    const board = await freshBoard(token)

    const res = await tasks.addTask(token, board.id, { title, status: 'todo' })
    expect(res.task.title).toBe(title)

    const page = await boards.loadBoardPage(token, board.id)
    const back = page.tasks.find((t: any) => t.id === res.task.id)
    expect(back).toBeTruthy()
    expect(back.title).toBe(title)
    expect(back.status).toBe('todo')
  })

  it('a SQL-injection payload cannot drop the tasks table', async () => {
    const { token } = await freshUser()
    const board = await freshBoard(token)
    await tasks.addTask(token, board.id, { title: "Robert'); DROP TABLE tasks;--", status: 'todo' })
    // The table must still exist and be queryable, with the row intact.
    const page = await boards.loadBoardPage(token, board.id)
    expect(Array.isArray(page.tasks)).toBe(true)
    expect(page.tasks.length).toBe(1)
    // Subsequent writes still work (schema intact).
    await tasks.addTask(token, board.id, { title: 'after-attack', status: 'done' })
    const page2 = await boards.loadBoardPage(token, board.id)
    expect(page2.tasks.length).toBe(2)
  })
})

describe('fuzz — malformed task titles are rejected cleanly, store unchanged', () => {
  it.each(REJECT_TITLES)('rejects a %s title and persists nothing', async (_label, title) => {
    const { token } = await freshUser()
    const board = await freshBoard(token)

    await expect(
      tasks.addTask(token, board.id, { title, status: 'todo' } as any),
    ).rejects.toThrow()

    const page = await boards.loadBoardPage(token, board.id)
    expect(page.tasks.length).toBe(0)
  })
})

describe('fuzz — invalid task status is rejected cleanly, store unchanged', () => {
  it.each<[string, unknown]>([
    ['unknown-string', 'archived'],
    ['empty', ''],
    ['null', null],
    ['undefined', undefined],
    ['number', 1],
    ['object', {}],
    ['injection', "todo'; DROP TABLE tasks;--"],
  ])('rejects status=%s on add and change', async (_label, status) => {
    const { token } = await freshUser()
    const board = await freshBoard(token)

    await expect(
      tasks.addTask(token, board.id, { title: 'ok', status } as any),
    ).rejects.toThrow()
    expect((await boards.loadBoardPage(token, board.id)).tasks.length).toBe(0)

    // Seed a valid task, then a bad status change must leave it untouched.
    const seeded = (await tasks.addTask(token, board.id, { title: 'seed', status: 'todo' })).task
    await expect(
      tasks.setTaskStatus(token, board.id, seeded.id, status as any),
    ).rejects.toThrow()
    const page = await boards.loadBoardPage(token, board.id)
    expect(page.tasks.find((t: any) => t.id === seeded.id).status).toBe('todo')
  })
})

describe('fuzz — malformed board names are rejected cleanly, store unchanged', () => {
  it.each<[string, unknown]>([
    ['empty', ''],
    ['whitespace-only', '   '],
    ['null', null],
    ['number', 42],
    ['object', {}],
    ['too-long', 'n'.repeat(10001)],
  ])('rejects a %s board name and creates no board', async (_label, name) => {
    const { token } = await freshUser()
    await expect(boards.createBoard(token, name as any)).rejects.toThrow()
    const page = await boards.loadBoardsPage(token)
    expect(page.boards.length).toBe(0)
  })

  it('accepts a hostile-but-valid board name and stores it verbatim', async () => {
    const { token } = await freshUser()
    const name = "<b>'); DROP TABLE boards;-- 日本語 🚀"
    const board = (await boards.createBoard(token, name)).board
    expect(board.name).toBe(name)
    const page = await boards.loadBoardsPage(token)
    expect(page.boards.length).toBe(1)
    expect(page.boards[0].name).toBe(name)
  })
})

describe('fuzz — malformed credentials are rejected cleanly, no account created', () => {
  it.each<[string, unknown]>([
    ['no-at-sign', 'not-an-email'],
    ['empty', ''],
    ['whitespace', '   '],
    ['null', null],
    ['undefined', undefined],
    ['number', 12345],
    ['object', {}],
    ['too-long', 'a'.repeat(400) + '@x.com'],
  ])('signUp rejects a %s email and persists no account', async (_label, email) => {
    await expect(auth.signUp(email as any, 'Pw-123456')).rejects.toThrow()
    if (typeof email === 'string' && email.length < 500) {
      expect(await db.getAccountByEmail(email)).toBeNull()
    }
  })

  it.each<[string, unknown]>([
    ['empty', ''],
    ['null', null],
    ['undefined', undefined],
    ['too-long', 'p'.repeat(1025)],
  ])('signUp rejects a %s password and persists no account', async (_label, password) => {
    const email = `badpw-${uid()}@example.com`
    await expect(auth.signUp(email, password as any)).rejects.toThrow()
    expect(await db.getAccountByEmail(email)).toBeNull()
  })

  it('an injection-shaped email is stored safely and cannot corrupt the users table', async () => {
    // Includes '@' so the format check passes; it must be stored as a literal value.
    const evilEmail = `a@b.com'); DROP TABLE users;--`
    const { token } = await auth.signUp(evilEmail, 'Pw-123456')
    expect(typeof token).toBe('string')
    // Table intact: a normal signup + login still works afterwards.
    const good = `good-${uid()}@example.com`
    await auth.signUp(good, 'Pw-123456')
    const res = await auth.logIn(good, 'Pw-123456')
    expect(res.token.length).toBeGreaterThan(0)
    // The literal email round-tripped, not executed.
    const rec = await db.getAccountByEmail(evilEmail.toLowerCase())
    expect(rec).toBeTruthy()
  })
})
