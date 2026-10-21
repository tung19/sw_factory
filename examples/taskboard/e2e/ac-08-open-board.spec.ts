import { test, expect } from '@playwright/test'
import { signupAndLand, createBoard, openBoard, addTask, taskItem, uniqueEmail } from './_shared'

// AC-8 — opening a board the user owns loads the board-detail page and lists that
// board's tasks.
test("AC-8: opening a board shows its tasks", async ({ page }) => {
  await signupAndLand(page, uniqueEmail('ac8'))

  const board = `Roadmap ${Date.now()}`
  await createBoard(page, board)
  await openBoard(page, board)

  // Seed two tasks on this board.
  await addTask(page, 'Write the brief', 'todo')
  await addTask(page, 'Ship the thing', 'doing')

  // Re-open the board from the list and confirm both tasks are listed.
  await page.goto('/boards')
  await openBoard(page, board)
  await expect(page.getByRole('heading', { name: board })).toBeVisible()
  await expect(taskItem(page, 'Write the brief')).toBeVisible()
  await expect(taskItem(page, 'Ship the thing')).toBeVisible()
})
