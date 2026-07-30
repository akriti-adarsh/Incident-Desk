import { createHmac } from 'node:crypto'

// Minimal RFC 6238 TOTP generator (SHA-1, 6 digits, 30s step) matching the
// backend's pyotp defaults. Avoids a fragile ESM/CJS dependency in the test.
const BASE32 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'

function base32Decode(input: string): Buffer {
  const clean = input.replace(/=+$/, '').toUpperCase()
  let bits = ''
  for (const ch of clean) {
    const idx = BASE32.indexOf(ch)
    if (idx === -1) continue
    bits += idx.toString(2).padStart(5, '0')
  }
  const bytes: number[] = []
  for (let i = 0; i + 8 <= bits.length; i += 8) {
    bytes.push(parseInt(bits.slice(i, i + 8), 2))
  }
  return Buffer.from(bytes)
}

export function totp(secret: string, atMs: number = Date.now()): string {
  const counter = Math.floor(atMs / 1000 / 30)
  const buf = Buffer.alloc(8)
  buf.writeBigInt64BE(BigInt(counter))
  const hmac = createHmac('sha1', base32Decode(secret)).update(buf).digest()
  const offset = hmac[hmac.length - 1] & 0x0f
  const code =
    ((hmac[offset] & 0x7f) << 24) |
    ((hmac[offset + 1] & 0xff) << 16) |
    ((hmac[offset + 2] & 0xff) << 8) |
    (hmac[offset + 3] & 0xff)
  return (code % 1_000_000).toString().padStart(6, '0')
}
