import { test, expect } from '@playwright/test'
import { signupAndLand, createBoard, uniqueEmail } from './_shared'

// AC-7 — the boards-list page lists exactly the signed-in user's own boards and no
// boards owned by other users.
test("AC-7: boards list shows only the user's own boards", async ({ page, browser }) => {
  const stamp = Date.now()
  const aBoard1 = `A-alpha-${stamp}`
  const aBoard2 = `A-beta-${stamp}`
  const bBoard = `B-SECRET-${stamp}`

  // User B (separate context/session) creates a board.
  const ctxB = await browser.newContext()
  const pageB = await ctxB.newPage()
  await signupAndLand(pageB, uniqueEmail('ac7b'))
  await createBoard(pageB, bBoard)
  await ctxB.close()

  // User A creates two boards.
  await signupAndLand(page, uniqueEmail('ac7a'))
  await createBoard(page, aBoard1)
  await createBoard(page, aBoard2)

  await page.goto('/boards')

  // Exactly A's two boards are listed.
  const links = page.locator('ul.list li a')
  await expect(links).toHaveCount(2)
  await expect(page.getByRole('link', { name: aBoard1 })).toBeVisible()
  await expect(page.getByRole('link', { name: aBoard2 })).toBeVisible()

  // B's board is not exposed to A.
  await expect(page.getByText(bBoard)).toHaveCount(0)
})
