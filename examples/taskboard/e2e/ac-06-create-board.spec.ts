import { test, expect } from '@playwright/test'
import { signupAndLand, createBoard, uniqueEmail } from './_shared'

// AC-6 — a logged-in user submits the create-board form → a new board owned by them is
// persisted and appears in their boards list.
test('AC-6: creating a board persists it and shows it in the list', async ({ page }) => {
  await signupAndLand(page, uniqueEmail('ac6'))

  const name = `Launch plan ${Date.now()}`
  await createBoard(page, name)

  await expect(page.getByRole('link', { name })).toBeVisible()

  // Persisted: a reload still shows it.
  await page.reload()
  await expect(page.getByRole('link', { name })).toBeVisible()
})
