import { expect, type Page, type APIRequestContext } from '@playwright/test'

export const API_BASE = process.env.E2E_API_BASE ?? 'http://localhost:8000'
export const MAILPIT = process.env.E2E_MAILPIT ?? 'http://localhost:58026'
export const SEED_PASSWORD = 'incident-desk-demo-9'

export function uniqueEmail(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`
}

// Pull a token link from Mailpit for a given address. When several emails go
// to one address (e.g. an invitation and a verification), `linkPath` selects
// the right one by the link it carries (e.g. "verify-email", "accept-invite").
export async function tokenFromEmail(
  request: APIRequestContext,
  address: string,
  linkPath?: string,
): Promise<string> {
  const pattern = linkPath
    ? new RegExp(`${linkPath}\\?token=([A-Za-z0-9_-]+)`)
    : /token=([A-Za-z0-9_-]+)/
  for (let attempt = 0; attempt < 30; attempt++) {
    const search = await request.get(
      `${MAILPIT}/api/v1/search?query=${encodeURIComponent(`to:"${address}"`)}`,
    )
    const body = await search.json()
    for (const message of body.messages ?? []) {
      const detail = await request.get(`${MAILPIT}/api/v1/message/${message.ID}`)
      const text = (await detail.json()).Text as string
      const match = text.match(pattern)
      if (match) return match[1]
    }
    await new Promise((r) => setTimeout(r, 500))
  }
  throw new Error(`no ${linkPath ?? 'token'} email arrived for ${address}`)
}

export async function login(page: Page, email: string, password = SEED_PASSWORD): Promise<void> {
  await page.goto('/login')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()
}

export async function loginSeedUser(page: Page, email: string): Promise<void> {
  await login(page, email)
  await expect(page.getByRole('heading', { name: 'Incidents' })).toBeVisible()
}
