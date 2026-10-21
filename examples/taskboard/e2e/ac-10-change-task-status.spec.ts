import { test, expect } from '@playwright/test'
import { signupAndLand, createBoard, openBoard, addTask, taskItem, uniqueEmail } from './_shared'

// AC-10 — using a task's status control to set a new status updates, persists, and
// reflects the task's status on the board-detail page.
test('AC-10: changing a task status updates and persists it', async ({ page }) => {
  await signupAndLand(page, uniqueEmail('ac10'))
  const board = `Status board ${Date.now()}`
  await createBoard(page, board)
  await openBoard(page, board)

  const title = `Movable task ${Date.now()}`
  await addTask(page, title, 'todo')

  const item = taskItem(page, title)
  await expect(item.locator('.badge')).toHaveText('todo')

  // Use the per-task status control to move it to "done".
  await item.getByLabel('Task status').selectOption('done')
  await item.getByRole('button', { name: 'Update' }).click()

  // Reflected on the board.
  const updated = taskItem(page, title)
  await expect(updated.locator('.badge')).toHaveText('done')

  // Persisted across a reload.
  await page.reload()
  await expect(taskItem(page, title).locator('.badge')).toHaveText('done')
})
