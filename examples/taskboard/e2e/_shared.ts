import path from 'node:path'
import { expect, type Page } from '@playwright/test'

// ---- single source of truth for the whole E2E run ----
// Everything (dev server, DB file, tests) is pinned to port 57151 per the task brief.
export const PORT = 57151
export const BASE_URL = `http://localhost:${PORT}`

// A dedicated, absolute DB file so the suite is isolated from any ./data/taskboard.db
// a human may have created. Resolved from cwd, which Playwright sets to this app root
// both when loading the config and when running a spec — so config and specs agree.
export const DB_PATH = path.resolve('data', 'e2e-taskboard.db')

// Stable secret so HMAC session tokens minted before the AC-12 restart still verify
// against the freshly-started server process.
export const SESSION_SECRET = 'area-e2e-fixed-secret'

// The env the dev server must run with. Used by the Playwright webServer block AND by
// the AC-12 test when it restarts the server itself.
export const SERVER_ENV = {
  TASKBOARD_DB: DB_PATH,
  SESSION_SECRET,
}

// A unique email per call so tests never collide on a shared, persistent DB.
let seq = 0
export function uniqueEmail(tag = 'user'): string {
  seq += 1
  return `${tag}-${Date.now()}-${process.pid}-${seq}@e2e.test`
}

// ---- UI-driven flows (interact THROUGH the page, never import app internals) ----

export async function signup(page: Page, email: string, password: string): Promise<void> {
  await page.goto('/login')
  await page.locator('#signup-email').fill(email)
  await page.locator('#signup-password').fill(password)
  await page.getByRole('button', { name: 'Create account' }).click()
}

export async function login(page: Page, email: string, password: string): Promise<void> {
  await page.goto('/login')
  await page.locator('#login-email').fill(email)
  await page.locator('#login-password').fill(password)
  await page.getByRole('button', { name: 'Log in' }).click()
}

// Signup + wait until we've landed on the boards list; returns the user's email.
export async function signupAndLand(page: Page, email: string, password = 'pw-correct-123'): Promise<void> {
  await signup(page, email, password)
  await expect(page).toHaveURL(/\/boards$/)
  await expect(page.getByRole('heading', { name: 'Your boards' })).toBeVisible()
}

// Create a board from the boards list and wait until it shows in the list.
export async function createBoard(page: Page, name: string): Promise<void> {
  await page.locator('#board-name').fill(name)
  await page.getByRole('button', { name: 'Create board' }).click()
  await expect(page).toHaveURL(/\/boards$/)
  await expect(page.getByRole('link', { name })).toBeVisible()
}

// Open a board by its link text and return its URL (which embeds the board id).
export async function openBoard(page: Page, name: string): Promise<string> {
  await page.getByRole('link', { name }).click()
  await expect(page.getByRole('heading', { name })).toBeVisible()
  return page.url()
}

// Add a task to the currently-open board and wait until it's rendered.
export async function addTask(page: Page, title: string, status: 'todo' | 'doing' | 'done'): Promise<void> {
  await page.locator('#task-title').fill(title)
  await page.locator('#task-status').selectOption(status)
  await page.getByRole('button', { name: 'Add task' }).click()
  await expect(page.getByRole('listitem').filter({ hasText: title })).toBeVisible()
}

// The <li> for a task, located by its title text.
export function taskItem(page: Page, title: string) {
  return page.getByRole('listitem').filter({ hasText: title })
}
