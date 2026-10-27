import Link from 'next/link'
import { redirect, notFound } from 'next/navigation'
import { loadBoardPage } from '@/lib/boards'
import { routes } from '@/lib/routes'
import { getSessionToken } from '@/lib/session'
import type { Status } from '@/lib/types'
import { addTaskAction } from '../../actions'
import TaskStatusControl from './TaskStatusControl'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

const STATUSES: Status[] = ['todo', 'doing', 'done']

export default async function BoardDetailPage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = await params
  const token = await getSessionToken()

  let page
  try {
    page = await loadBoardPage(token, id)
  } catch {
    // Authenticated but not the owner (or no such board) — don't leak existence.
    notFound()
  }

  if ('redirectTo' in page) redirect(page.redirectTo)

  const { board, tasks } = page

  return (
    <>
      <div className="topbar">
        <h1 style={{ margin: 0 }}>{board.name}</h1>
        <Link href={routes.boardsList}>← All boards</Link>
      </div>

      <div className="card">
        <form action={addTaskAction} className="row">
          <input type="hidden" name="boardId" value={board.id} />
          <div style={{ flex: 2 }}>
            <label htmlFor="task-title">New task</label>
            <input id="task-title" name="title" required placeholder="e.g. Draft the brief" />
          </div>
          <div style={{ flex: 1 }}>
            <label htmlFor="task-status">Status</label>
            <select id="task-status" name="status" defaultValue="todo">
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
          <button type="submit" style={{ flex: '0 0 auto' }}>
            Add task
          </button>
        </form>
      </div>

      {tasks.length === 0 ? (
        <p className="muted">No tasks yet — add one above.</p>
      ) : (
        <ul className="list">
          {tasks.map((task) => (
            <li key={task.id}>
              <span>
                <span className="badge" style={{ marginRight: '0.6rem' }}>
                  {task.status}
                </span>
                {task.title}
              </span>
              <TaskStatusControl boardId={board.id} taskId={task.id} status={task.status} />
            </li>
          ))}
        </ul>
      )}
    </>
  )
}
