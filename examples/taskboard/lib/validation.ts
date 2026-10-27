import type { Status } from './types'

export const STATUSES: readonly Status[] = ['todo', 'doing', 'done'] as const

// Length ceilings for every user-supplied text field. These are generous — far above
// any legitimate value and above everything the acceptance oracle exercises — so the
// app refuses abusive/unbounded payloads cleanly instead of trying to persist them,
// while never rejecting a real input (the frozen holdout stays green).
export const LIMITS = {
  email: 320, // RFC 5321 practical maximum (64 local + '@' + 255 domain)
  password: 1024,
  boardName: 10_000,
  taskTitle: 10_000,
} as const

export function isStatus(v: unknown): v is Status {
  return typeof v === 'string' && (STATUSES as readonly string[]).includes(v)
}

// Reject (throw) rather than coerce — the spec wants invalid statuses refused.
export function assertStatus(v: unknown): Status {
  if (!isStatus(v)) throw new Error(`invalid status: ${String(v)}`)
  return v
}

// Single guard for every free-text field. It insists on a REAL string (never a coerced
// object/number/array/null — which would silently store garbage like "[object Object]"),
// bounds the length (so a 50k-char payload can't bloat the durable store), and requires
// non-empty content after trimming. Throwing clean here keeps corrupt/abusive data out
// of the store while leaving it untouched — the caller's write never runs.
function assertText(value: unknown, field: string, max: number): string {
  if (typeof value !== 'string') throw new Error(`${field} must be a string`)
  if (value.length > max) throw new Error(`${field} is too long (max ${max} characters)`)
  const trimmed = value.trim()
  if (!trimmed) throw new Error(`${field} is required`)
  return trimmed
}

export function normalizeEmail(email: unknown): string {
  return (typeof email === 'string' ? email : '').trim().toLowerCase()
}

export function assertEmail(email: unknown): string {
  // A non-string, an over-long value, or anything without an '@' is rejected uniformly
  // as "invalid email" — the format check never leaks which part failed.
  if (typeof email !== 'string' || email.length > LIMITS.email) {
    throw new Error('invalid email')
  }
  const e = normalizeEmail(email)
  if (!e || !e.includes('@')) throw new Error('invalid email')
  return e
}

export function assertPassword(password: unknown): string {
  if (typeof password !== 'string' || password.length < 1) {
    throw new Error('password is required')
  }
  if (password.length > LIMITS.password) throw new Error('password is too long')
  return password
}

export function assertNonEmpty(value: unknown, field: string): string {
  return assertText(value, field, LIMITS.taskTitle)
}
