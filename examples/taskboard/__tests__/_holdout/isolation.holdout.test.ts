// LOCKED HOLDOUT — independent acceptance oracle (authored from the spec only).
// Covers AC-11. Do not edit after locking.
import { describe, it, expect, beforeAll } from 'vitest'
import os from 'node:os'
import path from 'node:path'
import crypto from 'node:crypto'

let auth: any
let boards: any
let tasks: any

beforeAll(async () => {
  process.env.TASKBOARD_DB = path.join(os.tmpdir(), `taskboard-holdout-isolation-${crypto.randomUUID()}.db`)
  auth = await import('../../lib/auth')
  boards = await import('../../lib/boards')
  tasks = await import('../../lib/tasks')
})

function uniqueEmail(prefix = 'user') {
  return `${prefix}-${crypto.randomUUID()}@example.com`
}

async function freshUser(prefix: string) {
  const email = uniqueEmail(prefix)
  const password = `Pw-${crypto.randomUUID()}`
  const { token, user } = await auth.signUp(email, password)
  return { email, password, token, user }
}

describe('AC-11 user-isolation', () => {
  it('denies user A any view or action on user B\'s board and tasks, and exposes none of B\'s data', async () => {
    const a = await freshUser('attacker-a')
    const b = await freshUser('victim-b')

    const bBoard = (await boards.createBoard(b.token, `B private ${crypto.randomUUID()}`)).board
    const bTask = (await tasks.addTask(b.token, bBoard.id, { title: 'B secret task', status: 'todo' })).task

    // A cannot VIEW B's board-detail page.
    await expect(boards.loadBoardPage(a.token, bBoard.id)).rejects.toThrow()

    // A cannot ACT on B's board (add a task).
    await expect(
      tasks.addTask(a.token, bBoard.id, { title: 'intrusion', status: 'todo' }),
    ).rejects.toThrow()

    // A cannot ACT on B's task (change its status).
    await expect(
      tasks.setTaskStatus(a.token, bBoard.id, bTask.id, 'done'),
    ).rejects.toThrow()

    // A's own boards list exposes none of B's boards.
    const aPage = await boards.loadBoardsPage(a.token)
    expect(aPage.boards.some((x: any) => x.id === bBoard.id)).toBe(false)

    // B's data is completely unchanged by A's attempts.
    const bPage = await boards.loadBoardPage(b.token, bBoard.id)
    const stillThere = bPage.tasks.find((t: any) => t.id === bTask.id)
    expect(stillThere).toBeTruthy()
    expect(stillThere.status).toBe('todo')
    expect(bPage.tasks.some((t: any) => t.title === 'intrusion')).toBe(false)
  })
})
