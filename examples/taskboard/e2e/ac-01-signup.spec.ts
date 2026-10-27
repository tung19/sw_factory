import { test, expect } from '@playwright/test'
import { signup, uniqueEmail } from './_shared'

// AC-1 — a visitor submits the signup form with a fresh email+password → account is
// created, they are logged in, and they land on the boards-list page.
test('AC-1: signup creates an account, logs in, and lands on the boards list', async ({ page, context }) => {
  const email = uniqueEmail('ac1')

  await signup(page, email, 'sup3r-secret-pw')

  // Logged in and taken to the boards-list page.
  await expect(page).toHaveURL(/\/boards$/)
  await expect(page.getByRole('heading', { name: 'Your boards' })).toBeVisible()
  // Their email is shown in the top bar — a visible sign the session is theirs.
  await expect(page.getByText(email)).toBeVisible()

  // A session cookie was created.
  const cookies = await context.cookies()
  expect(cookies.some((c) => c.name === 'sid' && c.value)).toBe(true)
})
