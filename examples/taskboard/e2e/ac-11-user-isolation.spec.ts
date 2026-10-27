import { test, expect } from '@playwright/test'
import { signupAndLand, createBoard, openBoard, addTask, uniqueEmail } from './_shared'

// AC-11 — user A cannot view or act on user B's board or tasks; none of B's boards or
// tasks are exposed to A.
test("AC-11: a user cannot access another user's board or tasks", async ({ page, browser }) => {
  const stamp = Date.now()
  const bBoard = `B-private-${stamp}`
  const bTask = `B-private-task-${stamp}`

  // User B owns a board with a task; capture its detail URL.
  const ctxB = await browser.newContext()
  const pageB = await ctxB.newPage()
  await signupAndLand(pageB, uniqueEmail('ac11b'))
  await createBoard(pageB, bBoard)
  const bBoardUrl = await openBoard(pageB, bBoard)
  await addTask(pageB, bTask, 'todo')
  await ctxB.close()

  expect(bBoardUrl).toMatch(/\/boards\/\d+$/)

  // User A logs in and tries to open B's board directly.
  await signupAndLand(page, uniqueEmail('ac11a'))
  const res = await page.goto(bBoardUrl)

  // Access denied (404 — existence is not even leaked) and none of B's data shown.
  expect(res?.status()).toBe(404)
  await expect(page.getByText(bBoard)).toHaveCount(0)
  await expect(page.getByText(bTask)).toHaveCount(0)

  // A's own boards list does not contain B's board either.
  await page.goto('/boards')
  await expect(page.getByText(bBoard)).toHaveCount(0)
})
