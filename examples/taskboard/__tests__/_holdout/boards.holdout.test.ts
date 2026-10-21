// LOCKED HOLDOUT — independent acceptance oracle (authored from the spec only).
// Covers AC-6, AC-7, AC-8. Do not edit after locking.
import { describe, it, expect, beforeAll } from 'vitest'
import os from 'node:os'
import path from 'node:path'
import crypto from 'node:crypto'

let auth: any
let boards: any
let tasks: any

beforeAll(async () => {
  process.env.TASKBOARD_DB = path.join(os.tmpdir(), `taskboard-holdout-boards-${crypto.randomUUID()}.db`)
  auth = await import('../../lib/auth')
  boards = await import('../../lib/boards')
  tasks = await import('../../lib/tasks')
})

function uniqueEmail(prefix = 'user') {
  return `${prefix}-${crypto.randomUUID()}@example.com`
}

// Each test gets its own freshly-signed-up (and therefore board-less) user, so the
// shared store never leaks another test's data into an assertion.
async function freshUser(prefix: string) {
  const email = uniqueEmail(prefix)
  const password = `Pw-${crypto.randomUUID()}`
  const { token, user } = await auth.signUp(email, password)
  return { email, password, token, user }
}

describe('AC-6 create-board', () => {
  it('persists a new board owned by the user and shows it in their boards list', async () => {
    const a = await freshUser('creator')
    const name = `My First Board ${crypto.randomUUID()}`

    const res = await boards.createBoard(a.token, name)
    expect(res.board).toMatchObject({ name })
    expect(res.board.id).toBeTruthy()
    expect(res.board.ownerId).toBe(a.user.id)

    const page = await boards.loadBoardsPage(a.token)
    const found = page.boards.find((b: any) => b.id === res.board.id)
    expect(found).toBeTruthy()
    expect(found.name).toBe(name)
    expect(found.ownerId).toBe(a.user.id)
  })
})

describe('AC-7 view-boards', () => {
  it('lists exactly the user\'s own boards and no boards owned by other users', async () => {
    const a = await freshUser('owner-a')
    const b = await freshUser('owner-b')

    const a1 = (await boards.createBoard(a.token, `A-One-${crypto.randomUUID()}`)).board
    const a2 = (await boards.createBoard(a.token, `A-Two-${crypto.randomUUID()}`)).board
    const b1 = (await boards.createBoard(b.token, `B-One-${crypto.randomUUID()}`)).board

    const page = await boards.loadBoardsPage(a.token)
    const ids = page.boards.map((x: any) => x.id).sort()
    expect(ids).toEqual([a1.id, a2.id].sort())

    for (const board of page.boards) expect(board.ownerId).toBe(a.user.id)
    expect(page.boards.some((x: any) => x.id === b1.id)).toBe(false)
  })
})

describe('AC-8 open-board', () => {
  it('loads the board-detail page and lists that board\'s tasks', async () => {
    const a = await freshUser('opener')
    const board = (await boards.createBoard(a.token, `Openable ${crypto.randomUUID()}`)).board
    const t1 = (await tasks.addTask(a.token, board.id, { title: 'Task one', status: 'todo' })).task
    const t2 = (await tasks.addTask(a.token, board.id, { title: 'Task two', status: 'doing' })).task

    const page = await boards.loadBoardPage(a.token, board.id)
    expect(page.redirectTo).toBeUndefined()
    expect(page.board).toMatchObject({ id: board.id, name: board.name })

    const titles = page.tasks.map((t: any) => t.title).sort()
    expect(titles).toEqual(['Task one', 'Task two'].sort())
    expect(page.tasks.some((t: any) => t.id === t1.id)).toBe(true)
    expect(page.tasks.some((t: any) => t.id === t2.id)).toBe(true)
    for (const t of page.tasks) expect(t.boardId).toBe(board.id)
  })
})
