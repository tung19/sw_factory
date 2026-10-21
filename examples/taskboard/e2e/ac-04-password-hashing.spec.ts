import { test, expect } from '@playwright/test'
import fs from 'node:fs'
import { DatabaseSync } from 'node:sqlite'
import { signup, uniqueEmail, DB_PATH } from './_shared'

// AC-4 — after signing up with a known plaintext password, the value stored in the
// persistent store is a hash that differs from the plaintext, and the plaintext never
// appears anywhere in storage.
//
// We drive signup THROUGH the UI, then read the durable store directly (node:sqlite is a
// Node builtin, not an app internal) to inspect what was actually persisted.
test('AC-4: the stored password is a hash, never the plaintext', async ({ page }) => {
  const email = uniqueEmail('ac4')
  // Distinctive plaintext so a raw-bytes scan of the DB file is meaningful.
  const plaintext = 'PlAiNtExT-must-NOT-be-stored-6f1a9c3e'

  await signup(page, email, plaintext)
  await expect(page).toHaveURL(/\/boards$/)

  // Read the account record back out of the persistent store.
  const db = new DatabaseSync(DB_PATH, { readOnly: true })
  let stored: string
  try {
    const row = db
      .prepare('SELECT passwordHash FROM users WHERE email = ? COLLATE NOCASE')
      .get(email) as { passwordHash?: string } | undefined
    expect(row, 'account row should exist in the store').toBeTruthy()
    stored = String(row!.passwordHash)
  } finally {
    db.close()
  }

  // The stored value is a hash, and it differs from the plaintext.
  expect(stored).not.toBe(plaintext)
  expect(stored).not.toContain(plaintext)
  expect(stored).toMatch(/^scrypt\$[0-9a-f]+\$[0-9a-f]+$/)

  // And the plaintext does not appear anywhere in the raw storage bytes.
  const raw = fs.readFileSync(DB_PATH)
  expect(raw.includes(Buffer.from(plaintext))).toBe(false)
})
