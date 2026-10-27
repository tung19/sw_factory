import { userFromToken } from './auth'
import { insertBoard, listBoardsByOwner, getBoardById, listTasksByBoard } from './db'
import { assertNonEmpty } from './validation'
import { routes } from './routes'
import type { Board, Task, User } from './types'

export type BoardsPage =
  | { redirectTo: string }
  | { user: User; boards: Board[] }

export type BoardPage =
  | { redirectTo: string }
  | { board: Board; tasks: Task[] }

export async function loadBoardsPage(token: string | undefined): Promise<BoardsPage> {
  const user = await userFromToken(token)
  if (!user) return { redirectTo: routes.login }
  return { user, boards: listBoardsByOwner(user.id) }
}

export async function createBoard(token: string, name: string): Promise<{ board: Board }> {
  const user = await userFromToken(token)
  if (!user) throw new Error('authentication required')
  const board = insertBoard(user.id, assertNonEmpty(name, 'board name'))
  return { board }
}

export async function loadBoardPage(
  token: string | undefined,
  boardId: string,
): Promise<BoardPage> {
  // Auth is checked BEFORE any resource lookup: an unauthenticated request is bounced
  // to login regardless of whether the board exists.
  const user = await userFromToken(token)
  if (!user) return { redirectTo: routes.login }

  const board = getBoardById(boardId)
  if (!board || board.ownerId !== user.id) {
    // Not owned (or non-existent) — deny without leaking existence.
    throw new Error('board not found')
  }
  return { board, tasks: listTasksByBoard(board.id) }
}
