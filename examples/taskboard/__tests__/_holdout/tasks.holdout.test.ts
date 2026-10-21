// LOCKED HOLDOUT — independent acceptance oracle (authored from the spec only).
// Covers AC-9, AC-10. Do not edit after locking.
import { describe, it, expect, beforeAll } from 'vitest'
import os from 'node:os'
import path from 'node:path'
import crypto from 'node:crypto'

let auth: any
let boards: any
let tasks: any

beforeAll(async () => {
  process.env.TASKBOARD_DB = path.join(os.tmpdir(), `taskboard-holdout-tasks-${crypto.randomUUID()}.db`)
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

async function freshBoard(user: any, prefix: string) {
  return (await boards.createBoard(user.token, `${prefix}-${crypto.randomUUID()}`)).board
}

describe('AC-9 add-task', () => {
  it.each(['todo', 'doing', 'done'])(
    'persists a new task with the given title and status "%s" and shows it on the board-detail page',
    async (status) => {
      const a = await freshUser('task-adder')
      const board = await freshBoard(a, 'TasksBoard')
      const title = `Add-task ${status} ${crypto.randomUUID()}`

      const res = await tasks.addTask(a.token, board.id, { title, status })
      expect(res.task).toMatchObject({ title, status, boardId: board.id })
      expect(res.task.id).toBeTruthy()

      const page = await boards.loadBoardPage(a.token, board.id)
      const found = page.tasks.find((t: any) => t.id === res.task.id)
      expect(found).toBeTruthy()
      expect(found.title).toBe(title)
      expect(found.status).toBe(status)
    },
  )

  it('rejects an add-task whose status is outside todo/doing/done', async () => {
    const a = await freshUser('task-adder-bad')
    const board = await freshBoard(a, 'BadStatusBoard')
    await expect(
      tasks.addTask(a.token, board.id, { title: 'nope', status: 'archived' }),
    ).rejects.toThrow()
  })
})

describe('AC-10 change-task-status', () => {
  it('updates and persists the task status and reflects it on the board-detail page', async () => {
    const a = await freshUser('status-changer')
    const board = await freshBoard(a, 'StatusBoard')
    const task = (await tasks.addTask(a.token, board.id, { title: 'Move me', status: 'todo' })).task

    const toDoing = await tasks.setTaskStatus(a.token, board.id, task.id, 'doing')
    expect(toDoing.task).toMatchObject({ id: task.id, status: 'doing' })

    let page = await boards.loadBoardPage(a.token, board.id)
    expect(page.tasks.find((t: any) => t.id === task.id).status).toBe('doing')

    const toDone = await tasks.setTaskStatus(a.token, board.id, task.id, 'done')
    expect(toDone.task.status).toBe('done')

    page = await boards.loadBoardPage(a.token, board.id)
    expect(page.tasks.find((t: any) => t.id === task.id).status).toBe('done')
  })

  it('rejects changing a task to a status outside todo/doing/done', async () => {
    const a = await freshUser('status-changer-bad')
    const board = await freshBoard(a, 'BadStatusBoard2')
    const task = (await tasks.addTask(a.token, board.id, { title: 'x', status: 'todo' })).task
    await expect(
      tasks.setTaskStatus(a.token, board.id, task.id, 'nonsense'),
    ).rejects.toThrow()
  })
})
