import { defineConfig, devices } from '@playwright/test'
import { BASE_URL, PORT, SERVER_ENV } from './e2e/_shared'

// Everything runs on port 57151 (port 3000 may be taken on this machine).
export default defineConfig({
  testDir: './e2e',
  // Shared, file-backed SQLite store means tests must not race each other, and AC-12
  // restarts the server in-process — so run strictly serially with a single worker.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [['list']],
  timeout: 60_000,
  expect: { timeout: 15_000 },
  globalSetup: './e2e/global-setup.ts',
  use: {
    baseURL: BASE_URL,
    navigationTimeout: 30_000,
    actionTimeout: 15_000,
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: `npm run dev -- -p ${PORT}`,
    url: BASE_URL,
    reuseExistingServer: false,
    timeout: 120_000,
    env: SERVER_ENV,
  },
})
