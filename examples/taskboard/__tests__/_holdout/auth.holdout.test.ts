// LOCKED HOLDOUT — independent acceptance oracle (authored from the spec only).
// Covers AC-1, AC-2, AC-3, AC-4, AC-5. Do not edit after locking.
import { describe, it, expect, beforeAll } from 'vitest'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import crypto from 'node:crypto'

let auth: any
let boards: any
let db: any
let routes: any
let DB_PATH: string

beforeAll(async () => {
  // The durable store lives at TASKBOARD_DB (a file path). Set it BEFORE importing
  // the app modules so they open the test store rather than any default location.
  DB_PATH = path.join(os.tmpdir(), `taskboard-holdout-auth-${crypto.randomUUID()}.db`)
  process.env.TASKBOARD_DB = DB_PATH
  auth = await import('../../lib/auth')
  boards = await import('../../lib/boards')
  db = await import('../../lib/db')
  ;({ routes } = await import('../../lib/routes'))
})

function uniqueEmail(prefix = 'user') {
  return `${prefix}-${crypto.randomUUID()}@example.com`
}

describe('AC-1 signup', () => {
  it('creates an account, logs the visitor in, and lands them on the boards-list page', async () => {
    const email = uniqueEmail('signup')
    const password = 'Signup-Pass-123!'

    const res = await auth.signUp(email, password)

    expect(res).toBeTruthy()
    expect(typeof res.token).toBe('string')
    expect(res.token.length).toBeGreaterThan(0)
    expect(res.user).toMatchObject({ email })
    expect(res.user.id).toBeTruthy()

    // "they land on the boards-list page"
    expect(res.redirectTo).toBe(routes.boardsList)

    // "they are logged in" — the returned session resolves to this user
    const guard = await auth.requireAuth(res.token)
    expect(guard.ok).toBe(true)
    expect(guard.user).toMatchObject({ email })

    // and that session can actually load the boards-list page (not bounced to login)
    const page = await boards.loadBoardsPage(res.token)
    expect(page.redirectTo).toBeUndefined()
    expect(Array.isArray(page.boards)).toBe(true)
  })

  it('rejects a second signup for an email that already has an account', async () => {
    const email = uniqueEmail('dup')
    const password = 'Dup-Pass-123!'
    await auth.signUp(email, password)
    await expect(auth.signUp(email, password)).rejects.toThrow()
  })
})

describe('AC-2 login', () => {
  it('logs in a visitor with correct credentials and takes them to the boards-list page', async () => {
    const email = uniqueEmail('login')
    const password = 'Login-Pass-123!'
    await auth.signUp(email, password)

    const res = await auth.logIn(email, password)

    expect(typeof res.token).toBe('string')
    expect(res.token.length).toBeGreaterThan(0)
    expect(res.user).toMatchObject({ email })
    expect(res.redirectTo).toBe(routes.boardsList)

    const guard = await auth.requireAuth(res.token)
    expect(guard.ok).toBe(true)
    expect(guard.user).toMatchObject({ email })
  })
})

describe('AC-3 login', () => {
  it('rejects the wrong password, creates no session, and keeps the visitor on the login page', async () => {
    const email = uniqueEmail('wrongpw')
    const password = 'Correct-Pass-123!'
    await auth.signUp(email, password)

    // Rejected → the call throws, so no token / session is handed back.
    await expect(auth.logIn(email, 'totally-wrong-password')).rejects.toThrow()

    // The account is intact and uncorrupted: the correct password still logs in.
    const ok = await auth.logIn(email, password)
    expect(typeof ok.token).toBe('string')
    expect(ok.token.length).toBeGreaterThan(0)
  })
})

describe('AC-4 password-hashing', () => {
  it('stores the password as a hash that differs from the plaintext and never stores the plaintext', async () => {
    const email = uniqueEmail('hash')
    const PLAINTEXT = 'PlAiNtExT-MARKER-9f3b21-do-not-store'
    await auth.signUp(email, PLAINTEXT)

    // The record read back from the persistent store holds a hash, not the plaintext.
    const record = await db.getAccountByEmail(email)
    expect(record).toBeTruthy()
    expect(record.email).toBe(email)
    expect(typeof record.passwordHash).toBe('string')
    expect(record.passwordHash.length).toBeGreaterThan(0)
    expect(record.passwordHash).not.toBe(PLAINTEXT)
    expect(record.passwordHash.includes(PLAINTEXT)).toBe(false)

    // The plaintext must not appear anywhere in the durable store bytes.
    expect(fs.existsSync(DB_PATH)).toBe(true)
    const raw = fs.readFileSync(DB_PATH).toString('latin1')
    expect(raw.includes(PLAINTEXT)).toBe(false)
  })
})

describe('AC-5 auth-guard', () => {
  it('redirects an unauthenticated visitor to login when requesting the boards-list page', async () => {
    for (const bad of [undefined, '', 'not-a-real-session-token']) {
      const guard = await auth.requireAuth(bad)
      expect(guard.ok).toBe(false)
      expect(guard.redirectTo).toBe(routes.login)

      const page = await boards.loadBoardsPage(bad)
      expect(page.redirectTo).toBe(routes.login)
      expect(page.boards).toBeUndefined()
    }
  })

  it('redirects an unauthenticated visitor to login when requesting a board-detail page', async () => {
    for (const bad of [undefined, '', 'not-a-real-session-token']) {
      const page = await boards.loadBoardPage(bad, 'any-board-id')
      expect(page.redirectTo).toBe(routes.login)
      expect(page.board).toBeUndefined()
      expect(page.tasks).toBeUndefined()
    }
  })
})
