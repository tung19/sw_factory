import { cookies } from 'next/headers'

// Thin cookie wrapper used only by the Next.js layer. The pure lib modules stay
// cookie-agnostic (they take a token argument), which keeps them unit-testable.
const COOKIE = 'sid'

export async function getSessionToken(): Promise<string | undefined> {
  const store = await cookies()
  return store.get(COOKIE)?.value
}

export async function setSessionToken(token: string): Promise<void> {
  const store = await cookies()
  store.set(COOKIE, token, {
    httpOnly: true,
    sameSite: 'lax',
    path: '/',
    secure: process.env.NODE_ENV === 'production',
    maxAge: 60 * 60 * 24 * 7,
  })
}

export async function clearSessionToken(): Promise<void> {
  const store = await cookies()
  store.delete(COOKIE)
}
