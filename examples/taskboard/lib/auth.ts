import { getAccountByEmail, getAccountById, createAccount } from './db'
import { hashPassword, verifyPassword } from './password'
import { signToken, verifyToken } from './token'
import { assertEmail, assertPassword } from './validation'
import { routes } from './routes'
import type { User } from './types'

export interface AuthResult {
  token: string
  user: User
  redirectTo: string
}

export async function signUp(email: string, password: string): Promise<AuthResult> {
  const e = assertEmail(email)
  const pw = assertPassword(password)
  if (await getAccountByEmail(e)) {
    throw new Error('an account already exists for this email')
  }
  const account = createAccount(e, hashPassword(pw))
  const user: User = { id: account.id, email: account.email }
  return { token: signToken(user.id), user, redirectTo: routes.boardsList }
}

export async function logIn(email: string, password: string): Promise<AuthResult> {
  const e = assertEmail(email)
  const pw = assertPassword(password)
  const account = await getAccountByEmail(e)
  if (!account || !verifyPassword(pw, account.passwordHash)) {
    // Unknown email or wrong password are indistinguishable to the caller.
    throw new Error('invalid email or password')
  }
  const user: User = { id: account.id, email: account.email }
  return { token: signToken(user.id), user, redirectTo: routes.boardsList }
}

export type Guard =
  | { ok: true; user: User }
  | { ok: false; redirectTo: string }

export async function requireAuth(token: string | undefined): Promise<Guard> {
  const user = await userFromToken(token)
  if (!user) return { ok: false, redirectTo: routes.login }
  return { ok: true, user }
}

// Internal helper shared by the boards/tasks layers: resolve a token to its live user
// (verifies the signature AND that the account still exists), or null.
export async function userFromToken(token: string | undefined): Promise<User | null> {
  const uid = verifyToken(token)
  if (!uid) return null
  const account = getAccountById(uid)
  return account ? { id: account.id, email: account.email } : null
}
