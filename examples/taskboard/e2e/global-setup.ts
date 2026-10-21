import fs from 'node:fs'
import { DB_PATH } from './_shared'

// Start every run from a clean, empty durable store so assertions about "exactly their
// own boards" and "the plaintext does not appear in storage" are deterministic. Runs
// before the webServer boots, so the file is never held open here.
export default function globalSetup() {
  for (const suffix of ['', '-wal', '-shm', '-journal']) {
    fs.rmSync(DB_PATH + suffix, { force: true })
  }
}
