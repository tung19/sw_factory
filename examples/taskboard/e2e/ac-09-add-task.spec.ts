import { test, expect } from '@playwright/test'
import { signupAndLand, createBoard, openBoard, addTask, taskItem, uniqueEmail } from './_shared'

// AC-9 — submitting the add-task form with a title and a status (todo/doing/done)
// persists a new task with that title and status and shows it on the board.
for (const status of ['todo', 'doing', 'done'] as const) {
  test(`AC-9: adding a task with status "${status}" persists and shows it`, async ({ page }) => {
    await signupAndLand(page, uniqueEmail(`ac9-${status}`))
    const board = `Board ${status} ${Date.now()}`
    await createBoard(page, board)
    await openBoard(page, board)

    const title = `Task ${status} ${Date.now()}`
    await addTask(page, title, status)

    // Shown with the chosen status badge.
    const item = taskItem(page, title)
    await expect(item).toBeVisible()
    await expect(item.locator('.badge')).toHaveText(status)

    // Persisted across a reload.
    await page.reload()
    const after = taskItem(page, title)
    await expect(after).toBeVisible()
    await expect(after.locator('.badge')).toHaveText(status)
  })
}
