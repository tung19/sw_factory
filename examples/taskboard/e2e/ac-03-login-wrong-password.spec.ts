import { test, expect } from '@playwright/test'
import { signupAndLand, login, uniqueEmail } from './_shared'

// AC-3 — logging in with the wrong password is rejected, creates no session, and leaves
// the visitor on the login page.
test('AC-3: login with wrong password is rejected and no session is created', async ({ page, context }) => {
  const email = uniqueEmail('ac3')

  await signupAndLand(page, email, 'the-right-password')
  await page.getByRole('button', { name: 'Log out' }).click()
  await expect(page).toHaveURL(/\/login$/)

  // Wrong password.
  await login(page, email, 'the-WRONG-password')

  // Still on the login page, with an error shown.
  await expect(page).toHaveURL(/\/login(\?|$)/)
  await expect(page.getByText('Incorrect email or password.')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Taskboard' })).toBeVisible()

  // No session cookie was set.
  const cookies = await context.cookies()
  expect(cookies.some((c) => c.name === 'sid' && c.value)).toBe(false)

  // And the guarded page still bounces us to login.
  await page.goto('/boards')
  await expect(page).toHaveURL(/\/login$/)
})
