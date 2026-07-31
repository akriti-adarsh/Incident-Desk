import { expect, test } from '@playwright/test'

import { loginSeedUser } from './helpers'

// Not part of the CI gate; run on demand to refresh the README screenshots:
//   npx playwright test screenshots --grep @screenshots
// (compose stack running, seeded).
const DIR = '../docs/screenshots'

test.describe('@screenshots', () => {
  test.use({ viewport: { width: 1360, height: 900 } })

  test('capture key screens', async ({ page }) => {
    await page.goto('/login')
    await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
    await page.screenshot({ path: `${DIR}/login.png` })

    await loginSeedUser(page, 'ada@example.com')
    await page.goto('/o/northwind/incidents')
    await expect(page.getByRole('heading', { name: 'Incidents' })).toBeVisible()
    await page.waitForTimeout(400)
    await page.screenshot({ path: `${DIR}/incidents.png` })

    await page.getByRole('listitem').first().getByRole('button').click()
    await expect(page.getByRole('region', { name: 'Timeline' })).toBeVisible()
    await page.waitForTimeout(400)
    await page.screenshot({ path: `${DIR}/incident-detail.png` })

    await page.goto('/o/northwind/metrics')
    await expect(page.getByRole('heading', { name: 'Metrics' })).toBeVisible()
    await page.waitForTimeout(800)
    await page.screenshot({ path: `${DIR}/metrics.png` })

    await page.goto('/o/northwind/settings')
    await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible()
    await page.waitForTimeout(300)
    await page.screenshot({ path: `${DIR}/settings.png` })
  })
})
