// CHAOS — concurrency.
//
// Hammers the store with many interleaved operations and asserts it stays consistent:
// no lost, duplicated, or corrupted records; ids stay globally unique; per-user
// isolation holds under load; and a uniqueness invariant (one account per email) is
// never violated by a race.
import { describe, it, expect, beforeAll } from 'vitest'
import os from 'node:os'
import path from 'node:path'
import crypto from 'node:crypto'

let auth: any
let boards: any
let tasks: any

beforeAll(async () => {
  process.env.TASKBOARD_DB = path.join(os.tmpdir(), `taskboard-chaos-conc-${crypto.randomUUID()}.db`)
  auth = await import('../../lib/auth')
  boards = await import('../../lib/boards')
  tasks = await import('../../lib/tasks')
})

function uid() {
  return crypto.randomUUID()
}

async function freshUser() {
  const { token, user } = await auth.signUp(`conc-${uid()}@example.com`, `Pw-${uid()}`)
  return { token, user }
}

describe('concurrency — interleaved writes stay consistent', () => {
  it('300 concurrent addTask calls all land with unique ids and none are lost', async () => {
    const { token } = await freshUser()
    const board = (await boards.createBoard(token, `C-${uid()}`)).board
    const N = 300

    const ids = await Promise.all(
      Array.from({ length: N }, (_, i) =>
        tasks.addTask(token, board.id, { title: `t-${i}`, status: 'todo' }).then((r: any) => r.task.id),
      ),
    )

    expect(ids.length).toBe(N)
    expect(new Set(ids).size).toBe(N) // all ids unique

    const page = await boards.loadBoardPage(token, board.id)
    expect(page.tasks.length).toBe(N) // nothing lost or duplicated
    const titles = new Set(page.tasks.map((t: any) => t.title))
    for (let i = 0; i < N; i++) expect(titles.has(`t-${i}`)).toBe(true)
    // every persisted task carries a valid status and belongs to this board
    for (const t of page.tasks) {
      expect(['todo', 'doing', 'done']).toContain(t.status)
      expect(t.boardId).toBe(board.id)
    }
  })

  it('mixed concurrent adds + status changes leave every task in a valid state', async () => {
    const { token } = await freshUser()
    const board = (await boards.createBoard(token, `C-${uid()}`)).board

    // Seed tasks, then concurrently add more AND flip statuses of the seeded ones.
    const seeded = await Promise.all(
      Array.from({ length: 50 }, (_, i) =>
        tasks.addTask(token, board.id, { title: `seed-${i}`, status: 'todo' }).then((r: any) => r.task),
      ),
    )

    const ops: Array<Promise<unknown>> = []
    for (let i = 0; i < 50; i++) {
      ops.push(tasks.addTask(token, board.id, { title: `extra-${i}`, status: 'doing' }))
      const target = seeded[i]
      const next = i % 2 === 0 ? 'doing' : 'done'
      ops.push(tasks.setTaskStatus(token, board.id, target.id, next))
    }
    await Promise.all(ops)

    const page = await boards.loadBoardPage(token, board.id)
    expect(page.tasks.length).toBe(100) // 50 seed + 50 extra, no corruption
    const seenIds = new Set(page.tasks.map((t: any) => t.id))
    expect(seenIds.size).toBe(100) // ids still unique
    for (const t of page.tasks) expect(['todo', 'doing', 'done']).toContain(t.status)
    // each seeded task reached its requested terminal status
    for (let i = 0; i < 50; i++) {
      const t = page.tasks.find((x: any) => x.id === seeded[i].id)
      expect(t.status).toBe(i % 2 === 0 ? 'doing' : 'done')
    }
  })

  it('concurrent board creation by two users keeps each list isolated', async () => {
    const a = await freshUser()
    const b = await freshUser()
    const PER = 40

    const [aBoards, bBoards] = await Promise.all([
      Promise.all(Array.from({ length: PER }, (_, i) => boards.createBoard(a.token, `A-${i}-${uid()}`))),
      Promise.all(Array.from({ length: PER }, (_, i) => boards.createBoard(b.token, `B-${i}-${uid()}`))),
    ])

    const aPage = await boards.loadBoardsPage(a.token)
    const bPage = await boards.loadBoardsPage(b.token)
    expect(aPage.boards.length).toBe(PER)
    expect(bPage.boards.length).toBe(PER)
    for (const board of aPage.boards) expect(board.ownerId).toBe(a.user.id)
    for (const board of bPage.boards) expect(board.ownerId).toBe(b.user.id)

    // globally-unique ids across both users' boards
    const allIds = [...aBoards, ...bBoards].map((r: any) => r.board.id)
    expect(new Set(allIds).size).toBe(PER * 2)
    // neither user sees the other's boards
    const bIds = new Set(bPage.boards.map((x: any) => x.id))
    expect(aPage.boards.some((x: any) => bIds.has(x.id))).toBe(false)
  })

  it('a race of signups for the SAME email yields exactly one account', async () => {
    const email = `race-${uid()}@example.com`
    const attempts = await Promise.allSettled(
      Array.from({ length: 12 }, () => auth.signUp(email, 'Pw-123456')),
    )
    const ok = attempts.filter((r) => r.status === 'fulfilled')
    expect(ok.length).toBe(1) // the UNIQUE-email invariant held under the race

    // Exactly one durable account exists and it can log in.
    const db = await import('../../lib/db')
    const rec = await db.getAccountByEmail(email)
    expect(rec).toBeTruthy()
    const res = await auth.logIn(email, 'Pw-123456')
    expect(res.token.length).toBeGreaterThan(0)
  })
})
