import { expect, test } from '@playwright/test'

import { loginSeedUser, SEED_PASSWORD, tokenFromEmail, uniqueEmail } from './helpers'
import { totp } from './totp'

// A change made in one browser context appears in another without a reload,
// proving the WebSocket fan-out reaches a second live client.
test('a new incident appears live in a second browser context', async ({ browser }) => {
  const ctxA = await browser.newContext()
  const ctxB = await browser.newContext()
  const pageA = await ctxA.newPage()
  const pageB = await ctxB.newPage()

  // Two members of northwind: ada (owner) reports, bruno (admin) watches.
  await loginSeedUser(pageA, 'ada@example.com')
  await pageA.goto('/o/northwind/incidents')
  await loginSeedUser(pageB, 'bruno@example.com')
  await pageB.goto('/o/northwind/incidents')

  const title = `Live update ${Date.now()}`

  // Report on A.
  await pageA.getByRole('button', { name: 'Report incident' }).click()
  const dialog = pageA.getByRole('dialog', { name: 'Report an incident' })
  await dialog.getByLabel('Service').selectOption({ index: 1 })
  await dialog.getByLabel('Title').fill(title)
  await dialog.getByLabel('Severity').selectOption('sev2')
  await dialog.getByRole('button', { name: 'Report incident' }).click()
  await expect(pageA.getByRole('heading', { name: title })).toBeVisible()

  // B, sitting on the list the whole time, sees it arrive live over the
  // WebSocket (no navigation), proving cross-client fan-out.
  await expect(pageB.getByText(title)).toBeVisible({ timeout: 25_000 })

  await ctxA.close()
  await ctxB.close()
})

// MFA enrolment and the login challenge. Uses a freshly registered account so
// the shared seed users stay password-only.
test('MFA enrolment then a challenged login', async ({ page, request }) => {
  const email = uniqueEmail('mfa')
  await page.goto('/register')
  await page.getByLabel('Full name').fill('MFA User')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(SEED_PASSWORD)
  await page.getByRole('button', { name: 'Create account' }).click()
  const verify = await tokenFromEmail(request, email, 'verify-email')
  await page.goto(`/verify-email?token=${verify}`)
  await page.getByRole('button', { name: 'Verify email' }).click()
  await expect(page.getByText('Your email is verified')).toBeVisible()

  // Log in and get an access token to drive MFA enrolment via the API (the
  // enrolment UI is out of the critical path; the challenge is what matters).
  const login = await request.post(
    `${process.env.E2E_API_BASE ?? 'http://localhost:8000'}/api/v1/auth/login`,
    { data: { email, password: SEED_PASSWORD } },
  )
  const token = (await login.json()).data.access_token
  const api = process.env.E2E_API_BASE ?? 'http://localhost:8000'
  const enroll = await request.post(`${api}/api/v1/auth/mfa/enroll`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  const secret = (await enroll.json()).data.secret
  await request.post(`${api}/api/v1/auth/mfa/verify`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { code: totp(secret) },
  })

  // Now the UI login must present the MFA challenge.
  await page.goto('/login')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(SEED_PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Enter your code' })).toBeVisible()

  // A code from the next timestep completes the challenge.
  await new Promise((r) => setTimeout(r, 30_000))
  await page.getByLabel('Authentication code').fill(totp(secret))
  await page.getByRole('button', { name: 'Verify and sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Incidents' }).or(page.getByRole('heading', { name: 'Create your organisation' }))).toBeVisible()
})
