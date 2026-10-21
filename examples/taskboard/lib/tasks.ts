import { userFromToken } from './auth'
import { getBoardById, insertTask, getTaskById, updateTaskStatus } from './db'
import { assertStatus, assertNonEmpty } from './validation'
import type { Board, Task, Status, User } from './types'

// Resolve the session user and assert they own the target board; throws otherwise.
// This is the single choke point that enforces per-user isolation for task writes.
async function requireOwnedBoard(
  token: string | undefined,
  boardId: string,
): Promise<{ user: User; board: Board }> {
  const user = await userFromToken(token)
  if (!user) throw new Error('authentication required')
  const board = getBoardById(boardId)
  if (!board || board.ownerId !== user.id) throw new Error('board not found')
  return { user, board }
}

export async function addTask(
  token: string,
  boardId: string,
  input: { title: string; status: Status },
): Promise<{ task: Task }> {
  const status = assertStatus(input?.status)
  const title = assertNonEmpty(input?.title, 'task title')
  const { board } = await requireOwnedBoard(token, boardId)
  return { task: insertTask(board.id, title, status) }
}

export async function setTaskStatus(
  token: string,
  boardId: string,
  taskId: string,
  status: Status,
): Promise<{ task: Task }> {
  const nextStatus = assertStatus(status)
  const { board } = await requireOwnedBoard(token, boardId)
  const task = getTaskById(taskId)
  if (!task || task.boardId !== board.id) throw new Error('task not found')
  const updated = updateTaskStatus(task.id, nextStatus)
  if (!updated) throw new Error('task not found')
  return { task: updated }
}
