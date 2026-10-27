import { test, expect } from '@playwright/test'

// AC-5 — a visitor who is not logged in is redirected to the login page when requesting
// either the boards-list page or a board-detail page.
test('AC-5: unauthenticated access to boards list redirects to login', async ({ page }) => {
  await page.goto('/boards')
  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByRole('heading', { name: 'Taskboard' })).toBeVisible()
})

test('AC-5: unauthenticated access to a board-detail page redirects to login', async ({ page }) => {
  // Some arbitrary board id — auth is checked before any board lookup, so this must
  // bounce to login (not 404).
  await page.goto('/boards/1')
  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByRole('heading', { name: 'Taskboard' })).toBeVisible()
})
