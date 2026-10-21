import { test, expect } from '@playwright/test'
import { spawn, execSync } from 'node:child_process'
import net from 'node:net'
import fs from 'node:fs'
import path from 'node:path'
import {
  signupAndLand,
  createBoard,
  openBoard,
  addTask,
  taskItem,
  login,
  uniqueEmail,
  PORT,
  BASE_URL,
  SERVER_ENV,
} from './_shared'

// AC-12 — after the server is restarted, the user's previously created boards and tasks
// are still present with the same data.
//
// This genuinely restarts the server: it kills the process listening on 57151 (the one
// Playwright started) and boots a brand-new `next dev` process on the SAME port against
// the SAME durable store file — a real new OS process reading back what was persisted.
// This spec is named to sort LAST and runs under a single worker, so no other test is
// in flight while the server is swapped.

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

function killPort(port: number): void {
  try {
    // -sTCP:LISTEN restricts to the LISTENER only. A bare `lsof -ti tcp:<port>` would
    // also match client connections (the browser, this worker's fetch) and killing
    // those would take down the test worker itself.
    const pids = execSync(`lsof -ti tcp:${port} -sTCP:LISTEN`, { stdio: ['ignore', 'pipe', 'ignore'] })
      .toString()
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean)
    for (const pid of pids) {
      try {
        process.kill(Number(pid), 'SIGKILL')
      } catch {
        /* already gone */
      }
    }
  } catch {
    /* nothing listening */
  }
}

async function waitPortFree(port: number, timeoutMs = 20_000): Promise<void> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const free = await new Promise<boolean>((resolve) => {
      const sock = net.connect(port, '127.0.0.1')
      sock.once('connect', () => {
        sock.destroy()
        resolve(false)
      })
      sock.once('error', () => resolve(true))
    })
    if (free) return
    await sleep(300)
  }
  throw new Error(`port ${port} did not free up`)
}

async function waitServerUp(timeoutMs = 90_000): Promise<void> {
  const deadline = Date.now() + timeoutMs
  let lastErr = 'unknown'
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${BASE_URL}/login`, { redirect: 'manual' })
      if (res.status === 200) return
      lastErr = `status ${res.status}`
    } catch (e) {
      lastErr = String((e as Error)?.message ?? e)
    }
    await sleep(500)
  }
  throw new Error(`server did not come up on ${BASE_URL}: ${lastErr}`)
}

test('AC-12: boards and tasks survive a server restart', async ({ page, browser }) => {
  test.setTimeout(150_000)

  const email = uniqueEmail('ac12')
  const password = 'durable-pw-123'
  const board = `Durable board ${Date.now()}`
  const task = `Durable task ${Date.now()}`

  // 1) Create data through the UI on the currently-running server.
  await signupAndLand(page, email, password)
  await createBoard(page, board)
  await openBoard(page, board)
  await addTask(page, task, 'doing')
  await expect(taskItem(page, task).locator('.badge')).toHaveText('doing')

  // 2) Restart the server: kill the listener on 57151, then boot a fresh process on the
  //    same port against the same DB file.
  killPort(PORT)
  await waitPortFree(PORT)

  const logPath = path.resolve('.taskboard_e2e_restart.log')
  const out = fs.openSync(logPath, 'a')
  const child = spawn('npm', ['run', 'dev', '--', '-p', String(PORT)], {
    cwd: process.cwd(),
    env: { ...process.env, ...SERVER_ENV },
    stdio: ['ignore', out, out],
    detached: true,
  })
  child.unref()

  try {
    await waitServerUp()

    // 3) A brand-new client (fresh cookies) logs in again after the restart.
    const ctx = await browser.newContext()
    const page2 = await ctx.newPage()
    await login(page2, email, password)
    await expect(page2).toHaveURL(/\/boards$/)

    // 4) Their board and task are still present with the same data.
    await expect(page2.getByRole('link', { name: board })).toBeVisible()
    await openBoard(page2, board)
    await expect(taskItem(page2, task)).toBeVisible()
    await expect(taskItem(page2, task).locator('.badge')).toHaveText('doing')

    await ctx.close()
  } finally {
    // Tear down the server we started, leaving the port clean.
    try {
      process.kill(-child.pid!, 'SIGKILL')
    } catch {
      /* ignore */
    }
    killPort(PORT)
    fs.closeSync(out)
  }
})
