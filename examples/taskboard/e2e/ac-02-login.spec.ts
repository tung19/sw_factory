import { test, expect } from '@playwright/test'
import { signupAndLand, login, uniqueEmail } from './_shared'

// AC-2 — with an existing account, logging in with the correct email+password logs the
// visitor in and takes them to the boards-list page.
test('AC-2: login with correct credentials lands on the boards list', async ({ page }) => {
  const email = uniqueEmail('ac2')
  const password = 'correct-horse-battery'

  // Create the account first, then log out so we start from a clean, logged-out state.
  await signupAndLand(page, email, password)
  await page.getByRole('button', { name: 'Log out' }).click()
  await expect(page).toHaveURL(/\/login$/)

  // Now log in with the correct credentials.
  await login(page, email, password)

  await expect(page).toHaveURL(/\/boards$/)
  await expect(page.getByRole('heading', { name: 'Your boards' })).toBeVisible()
  await expect(page.getByText(email)).toBeVisible()
})
