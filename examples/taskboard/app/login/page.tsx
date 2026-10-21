import { redirect } from 'next/navigation'
import { requireAuth } from '@/lib/auth'
import { routes } from '@/lib/routes'
import { getSessionToken } from '@/lib/session'
import { loginAction, signupAction } from '../actions'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

const MESSAGES: Record<string, string> = {
  invalid: 'Incorrect email or password.',
  signup: 'Could not sign up — that email may already be registered.',
}

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>
}) {
  // Already logged in? Skip the login page.
  const guard = await requireAuth(await getSessionToken())
  if (guard.ok) redirect(routes.boardsList)

  const { error } = await searchParams
  const message = error ? MESSAGES[error] ?? 'Something went wrong.' : null

  return (
    <>
      <h1>Taskboard</h1>
      <p className="muted">Sign in or create an account to manage your boards.</p>
      {message && <p className="error">{message}</p>}

      <div className="card">
        <h2 style={{ marginTop: 0, fontSize: '1.1rem' }}>Log in</h2>
        <form action={loginAction}>
          <div style={{ marginBottom: '0.75rem' }}>
            <label htmlFor="login-email">Email</label>
            <input id="login-email" name="email" type="email" required autoComplete="email" />
          </div>
          <div style={{ marginBottom: '1rem' }}>
            <label htmlFor="login-password">Password</label>
            <input
              id="login-password"
              name="password"
              type="password"
              required
              autoComplete="current-password"
            />
          </div>
          <button type="submit">Log in</button>
        </form>
      </div>

      <div className="card">
        <h2 style={{ marginTop: 0, fontSize: '1.1rem' }}>Sign up</h2>
        <form action={signupAction}>
          <div style={{ marginBottom: '0.75rem' }}>
            <label htmlFor="signup-email">Email</label>
            <input id="signup-email" name="email" type="email" required autoComplete="email" />
          </div>
          <div style={{ marginBottom: '1rem' }}>
            <label htmlFor="signup-password">Password</label>
            <input
              id="signup-password"
              name="password"
              type="password"
              required
              autoComplete="new-password"
            />
          </div>
          <button type="submit">Create account</button>
        </form>
      </div>
    </>
  )
}
