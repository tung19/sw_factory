import { scryptSync, randomBytes, timingSafeEqual } from 'node:crypto'

// Stored format: scrypt$<saltHex>$<hashHex>. The plaintext is never persisted.
const KEYLEN = 64

export function hashPassword(plaintext: string): string {
  const salt = randomBytes(16)
  const hash = scryptSync(plaintext, salt, KEYLEN)
  return `scrypt$${salt.toString('hex')}$${hash.toString('hex')}`
}

export function verifyPassword(plaintext: string, stored: string): boolean {
  const parts = String(stored ?? '').split('$')
  if (parts.length !== 3 || parts[0] !== 'scrypt') return false
  const [, saltHex, hashHex] = parts
  if (!saltHex || !hashHex) return false
  const salt = Buffer.from(saltHex, 'hex')
  const expected = Buffer.from(hashHex, 'hex')
  const actual = scryptSync(plaintext, salt, expected.length)
  return expected.length === actual.length && timingSafeEqual(expected, actual)
}
