import Link from 'next/link'
import { redirect } from 'next/navigation'
import { loadBoardsPage } from '@/lib/boards'
import { routes } from '@/lib/routes'
import { getSessionToken } from '@/lib/session'
import { createBoardAction, logoutAction } from '../actions'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export default async function BoardsPage() {
  const page = await loadBoardsPage(await getSessionToken())
  if ('redirectTo' in page) redirect(page.redirectTo)

  const { user, boards } = page

  return (
    <>
      <div className="topbar">
        <h1 style={{ margin: 0 }}>Your boards</h1>
        <form action={logoutAction}>
          <span className="muted" style={{ marginRight: '0.75rem' }}>
            {user.email}
          </span>
          <button className="ghost" type="submit">
            Log out
          </button>
        </form>
      </div>

      <div className="card">
        <form action={createBoardAction} className="row">
          <div>
            <label htmlFor="board-name">New board name</label>
            <input id="board-name" name="name" required placeholder="e.g. Launch plan" />
          </div>
          <button type="submit" style={{ flex: '0 0 auto' }}>
            Create board
          </button>
        </form>
      </div>

      {boards.length === 0 ? (
        <p className="muted">No boards yet — create your first one above.</p>
      ) : (
        <ul className="list">
          {boards.map((board) => (
            <li key={board.id}>
              <Link href={routes.board(board.id)}>{board.name}</Link>
            </li>
          ))}
        </ul>
      )}
    </>
  )
}
