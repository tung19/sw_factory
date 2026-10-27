'use server'

import { redirect } from 'next/navigation'
import { revalidatePath } from 'next/cache'
import { signUp, logIn } from '@/lib/auth'
import { createBoard } from '@/lib/boards'
import { addTask, setTaskStatus } from '@/lib/tasks'
import { routes } from '@/lib/routes'
import { getSessionToken, setSessionToken, clearSessionToken } from '@/lib/session'
import { assertStatus } from '@/lib/validation'

export async function signupAction(formData: FormData): Promise<void> {
  const email = String(formData.get('email') ?? '')
  const password = String(formData.get('password') ?? '')
  try {
    const res = await signUp(email, password)
    await setSessionToken(res.token)
  } catch {
    redirect(`${routes.login}?error=signup`)
  }
  redirect(routes.boardsList)
}

export async function loginAction(formData: FormData): Promise<void> {
  const email = String(formData.get('email') ?? '')
  const password = String(formData.get('password') ?? '')
  try {
    const res = await logIn(email, password)
    await setSessionToken(res.token)
  } catch {
    redirect(`${routes.login}?error=invalid`)
  }
  redirect(routes.boardsList)
}

export async function logoutAction(): Promise<void> {
  await clearSessionToken()
  redirect(routes.login)
}

export async function createBoardAction(formData: FormData): Promise<void> {
  const token = await getSessionToken()
  const name = String(formData.get('name') ?? '')
  try {
    await createBoard(token ?? '', name)
  } catch {
    redirect(routes.boardsList)
  }
  revalidatePath(routes.boardsList)
  redirect(routes.boardsList)
}

export async function addTaskAction(formData: FormData): Promise<void> {
  const token = await getSessionToken()
  const boardId = String(formData.get('boardId') ?? '')
  const title = String(formData.get('title') ?? '')
  const statusRaw = String(formData.get('status') ?? 'todo')
  try {
    const status = assertStatus(statusRaw)
    await addTask(token ?? '', boardId, { title, status })
  } catch {
    // fall through to re-render the board; invalid input simply isn't added
  }
  revalidatePath(routes.board(boardId))
  redirect(routes.board(boardId))
}

export async function changeTaskStatusAction(formData: FormData): Promise<void> {
  const token = await getSessionToken()
  const boardId = String(formData.get('boardId') ?? '')
  const taskId = String(formData.get('taskId') ?? '')
  const statusRaw = String(formData.get('status') ?? '')
  try {
    const status = assertStatus(statusRaw)
    await setTaskStatus(token ?? '', boardId, taskId, status)
  } catch {
    // ignore invalid transitions / non-owner attempts
  }
  revalidatePath(routes.board(boardId))
  redirect(routes.board(boardId))
}
