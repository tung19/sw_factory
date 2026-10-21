import { redirect } from 'next/navigation'
import { requireAuth } from '@/lib/auth'
import { routes } from '@/lib/routes'
import { getSessionToken } from '@/lib/session'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export default async function Home() {
  const guard = await requireAuth(await getSessionToken())
  redirect(guard.ok ? routes.boardsList : routes.login)
}
