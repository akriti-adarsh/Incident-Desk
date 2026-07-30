import { expect, test } from '@playwright/test'

import { API_BASE, loginSeedUser, SEED_PASSWORD } from './helpers'

// Permission gating: a viewer cannot see the resolve/report controls, and the
// API rejects the action even if called directly. Uses the seeded data
// (kofi is a viewer in atlas; chen is its owner).
test('a viewer cannot report incidents in the UI or via the API', async ({ page, request }) => {
  await loginSeedUser(page, 'kofi@example.com')

  // Kofi is a viewer in atlas: the Report incident button is absent.
  await page.goto('/o/atlas/incidents')
  await expect(page.getByRole('heading', { name: 'Incidents' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Report incident' })).toHaveCount(0)

  // The Settings API-keys and Audit-log tabs (admin only) are absent too.
  await page.goto('/o/atlas/settings')
  await expect(page.getByRole('tab', { name: 'API keys' })).toHaveCount(0)
  await expect(page.getByRole('tab', { name: 'Audit log' })).toHaveCount(0)

  // The backend rejects a direct create call from the viewer.
  const login = await request.post(`${API_BASE}/api/v1/auth/login`, {
    data: { email: 'kofi@example.com', password: SEED_PASSWORD },
  })
  const token = (await login.json()).data.access_token
  const services = await request.get(`${API_BASE}/api/v1/orgs/atlas/services`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  const serviceId = (await services.json()).data[0].id
  const create = await request.post(`${API_BASE}/api/v1/orgs/atlas/incidents`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { service_id: serviceId, title: 'sneaky', severity: 'sev3' },
    failOnStatusCode: false,
  })
  expect(create.status()).toBe(403)
})

test('cross-tenant access is a 404, not a 403', async ({ page, request }) => {
  await loginSeedUser(page, 'kofi@example.com')
  const login = await request.post(`${API_BASE}/api/v1/auth/login`, {
    data: { email: 'kofi@example.com', password: SEED_PASSWORD },
  })
  const token = (await login.json()).data.access_token
  // Kofi is not a member of helios; the org answers 404 (existence not leaked).
  const response = await request.get(`${API_BASE}/api/v1/orgs/helios/incidents`, {
    headers: { Authorization: `Bearer ${token}` },
    failOnStatusCode: false,
  })
  expect(response.status()).toBe(404)
})
