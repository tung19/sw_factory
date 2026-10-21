// CHAOS — failure injection.
//
// Forces an internal dependency (a store write, the password hasher, an account read)
// to throw mid-operation and asserts the public operation fails CLEANLY — it rejects,
// leaves the durable store exactly as it was (no partial write), and the system fully
// recovers once the fault clears. Each public mutation is a single SQLite statement, so
// "no partial write" is a structural guarantee; these tests lock it against regressions.
import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest'
import os from 'node:os'
import path from 'node:path'
import crypto from 'node:crypto'

let auth: any
let boards: any
let tasks: any
let db: any
let password: any

beforeAll(async () => {
  process.env.TASKBOARD_DB = path.join(os.tmpdir(), `taskboard-chaos-fault-${crypto.randomUUID()}.db`)
  auth = await import('../../lib/auth')
  boards = await import('../../lib/boards')
  tasks = await import('../../lib/tasks')
  db = await import('../../lib/db')
  password = await import('../../lib/password')
})

afterEach(() => {
  vi.restoreAllMocks()
})

function uid() {
  return crypto.randomUUID()
}

async function freshUser() {
  const { token, user } = await auth.signUp(`fault-${uid()}@example.com`, `Pw-${uid()}`)
  return { token, user }
}

const BOOM = () => {
  throw new Error('INJECTED dependency failure')
}

describe('failure injection — a throwing store write fails cleanly, store unchanged', () => {
  it('addTask: insertTask throws → rejects and persists nothing', async () => {
    const { token } = await freshUser()
    const board = (await boards.createBoard(token, `F-${uid()}`)).board

    const spy = vi.spyOn(db, 'insertTask').mockImplementation(BOOM)
    await expect(tasks.addTask(token, board.id, { title: 'x', status: 'todo' })).rejects.toThrow(
      /INJECTED/,
    )
    spy.mockRestore()

    // No phantom/partial task was written.
    expect((await boards.loadBoardPage(token, board.id)).tasks.length).toBe(0)
    // And the operation works normally once the fault clears.
    await tasks.addTask(token, board.id, { title: 'recovered', status: 'todo' })
    expect((await boards.loadBoardPage(token, board.id)).tasks.length).toBe(1)
  })

  it('createBoard: insertBoard throws → rejects and creates no board', async () => {
    const { token } = await freshUser()
    const spy = vi.spyOn(db, 'insertBoard').mockImplementation(BOOM)
    await expect(boards.createBoard(token, 'nope')).rejects.toThrow(/INJECTED/)
    spy.mockRestore()

    expect((await boards.loadBoardsPage(token)).boards.length).toBe(0)
    await boards.createBoard(token, 'ok')
    expect((await boards.loadBoardsPage(token)).boards.length).toBe(1)
  })

  it('setTaskStatus: updateTaskStatus throws → rejects and leaves the old status', async () => {
    const { token } = await freshUser()
    const board = (await boards.createBoard(token, `F-${uid()}`)).board
    const task = (await tasks.addTask(token, board.id, { title: 't', status: 'todo' })).task

    const spy = vi.spyOn(db, 'updateTaskStatus').mockImplementation(BOOM)
    await expect(tasks.setTaskStatus(token, board.id, task.id, 'done')).rejects.toThrow(/INJECTED/)
    spy.mockRestore()

    const page = await boards.loadBoardPage(token, board.id)
    expect(page.tasks.find((t: any) => t.id === task.id).status).toBe('todo') // unchanged
    // recovery
    await tasks.setTaskStatus(token, board.id, task.id, 'done')
    const page2 = await boards.loadBoardPage(token, board.id)
    expect(page2.tasks.find((t: any) => t.id === task.id).status).toBe('done')
  })
})

describe('failure injection — a throwing auth dependency fails cleanly, no account', () => {
  it('signUp: createAccount throws → rejects and persists no account', async () => {
    const email = `fi-create-${uid()}@example.com`
    const spy = vi.spyOn(db, 'createAccount').mockImplementation(BOOM)
    await expect(auth.signUp(email, 'Pw-123456')).rejects.toThrow(/INJECTED/)
    spy.mockRestore()

    expect(await db.getAccountByEmail(email)).toBeNull()
    // recovery: the same email can now sign up successfully.
    const res = await auth.signUp(email, 'Pw-123456')
    expect(res.token.length).toBeGreaterThan(0)
  })

  it('signUp: hashPassword throws → rejects before any account is written', async () => {
    const email = `fi-hash-${uid()}@example.com`
    const spy = vi.spyOn(password, 'hashPassword').mockImplementation(BOOM)
    await expect(auth.signUp(email, 'Pw-123456')).rejects.toThrow(/INJECTED/)
    spy.mockRestore()

    expect(await db.getAccountByEmail(email)).toBeNull()
  })

  it('logIn: getAccountByEmail throws → rejects cleanly and recovers', async () => {
    const email = `fi-read-${uid()}@example.com`
    await auth.signUp(email, 'Pw-123456')

    const spy = vi.spyOn(db, 'getAccountByEmail').mockImplementation(BOOM)
    await expect(auth.logIn(email, 'Pw-123456')).rejects.toThrow(/INJECTED/)
    spy.mockRestore()

    // The account was never touched by the failed read; login works again.
    const res = await auth.logIn(email, 'Pw-123456')
    expect(res.token.length).toBeGreaterThan(0)
  })
})
