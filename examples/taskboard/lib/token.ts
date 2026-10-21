import { createHmac, timingSafeEqual } from 'node:crypto'

// Stateless HMAC-signed session token: base64url(payload).base64url(signature).
// Carries only the user id; integrity is checked on every requireAuth call. The
// secret is stable across module reloads/restarts so tokens minted before a restart
// still verify (dev fallback is constant; set SESSION_SECRET in production).
const SECRET = process.env.SESSION_SECRET || 'area-taskboard-dev-secret-change-me'

function sign(payload: string): string {
  return createHmac('sha256', SECRET).update(payload).digest('base64url')
}

export function signToken(userId: string): string {
  const payload = Buffer.from(JSON.stringify({ uid: userId })).toString('base64url')
  return `${payload}.${sign(payload)}`
}

export function verifyToken(token: string | undefined | null): string | null {
  if (!token || typeof token !== 'string') return null
  const dot = token.lastIndexOf('.')
  if (dot <= 0) return null
  const payload = token.slice(0, dot)
  const providedSig = token.slice(dot + 1)
  const expectedSig = sign(payload)
  const a = Buffer.from(providedSig)
  const b = Buffer.from(expectedSig)
  if (a.length !== b.length || !timingSafeEqual(a, b)) return null
  try {
    const obj = JSON.parse(Buffer.from(payload, 'base64url').toString('utf8'))
    if (!obj || typeof obj.uid !== 'string' || !obj.uid) return null
    return obj.uid
  } catch {
    return null
  }
}
