// LOCKED HOLDOUT — independent acceptance oracle (authored from the spec only).
// Covers AC-12. Do not edit after locking.
//
// "Server restart" is simulated by dropping every in-memory module instance with
// vi.resetModules() and re-importing the app modules fresh. If the data lived only
// in process memory, the fresh modules would start empty and these assertions fail;
// they pass only when the store is durably persisted (via process.env.TASKBOARD_DB).
import { describe, it, expect, beforeAll, vi } from 'vitest'
import os from 'node:os'
import path from 'node:path'
import crypto from 'node:crypto'

beforeAll(() => {
  // A single stable store path that survives the simulated restart.
  process.env.TASKBOARD_DB = path.join(os.tmpdir(), `taskboard-holdout-durability-${crypto.randomUUID()}.db`)
})

describe('AC-12 durable-persistence', () => {
  it('still has the user\'s boards and tasks (same data) after the server is restarted', async () => {
    const email = `persist-${crypto.randomUUID()}@example.com`
    const password = `Persist-Pass-${crypto.randomUUID()}`
    const boardName = `Durable Board ${crypto.randomUUID()}`
    const taskTitle = `Durable Task ${crypto.randomUUID()}`

    // --- first "server process": create the account, a board, and a task ---
    {
      const auth = await import('../../lib/auth')
      const boards = await import('../../lib/boards')
      const tasks = await import('../../lib/tasks')

      const { token } = await auth.signUp(email, password)
      const board = (await boards.createBoard(token, boardName)).board
      await tasks.addTask(token, board.id, { title: taskTitle, status: 'doing' })
    }

    // --- restart: discard all module (and thus in-memory) state ---
    vi.resetModules()

    // --- second "server process": fresh imports must read the durable store ---
    {
      const auth = await import('../../lib/auth')
      const boards = await import('../../lib/boards')

      // The account itself survived — the user can log in again.
      const { token } = await auth.logIn(email, password)

      // The board is still present with the same name.
      const listPage = await boards.loadBoardsPage(token)
      const board = listPage.boards.find((b: any) => b.name === boardName)
      expect(board).toBeTruthy()

      // The task is still present with the same title and status.
      const detail = await boards.loadBoardPage(token, board.id)
      const task = detail.tasks.find((t: any) => t.title === taskTitle)
      expect(task).toBeTruthy()
      expect(task.status).toBe('doing')
    }
  })
})
