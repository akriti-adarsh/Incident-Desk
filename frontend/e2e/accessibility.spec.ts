import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

import { loginSeedUser } from './helpers'

// The axe accessibility scan, run on the primary screens against WCAG 2 A/AA.
// Any violation fails the build.
const RULES = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']

test.describe('accessibility', () => {
  test('login screen has no violations', async ({ page }) => {
    await page.goto('/login')
    await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
    const results = await new AxeBuilder({ page }).withTags(RULES).analyze()
    expect(results.violations).toEqual([])
  })

  test('incident list has no violations', async ({ page }) => {
    await loginSeedUser(page, 'ada@example.com')
    await page.goto('/o/northwind/incidents')
    await expect(page.getByRole('heading', { name: 'Incidents' })).toBeVisible()
    const results = await new AxeBuilder({ page }).withTags(RULES).analyze()
    expect(results.violations).toEqual([])
  })

  test('incident detail has no violations', async ({ page }) => {
    await loginSeedUser(page, 'ada@example.com')
    await page.goto('/o/northwind/incidents')
    await page.getByRole('listitem').first().getByRole('button').click()
    await expect(page.getByRole('region', { name: 'Timeline' })).toBeVisible()
    const results = await new AxeBuilder({ page }).withTags(RULES).analyze()
    expect(results.violations).toEqual([])
  })

  test('metrics dashboard has no violations', async ({ page }) => {
    await loginSeedUser(page, 'ada@example.com')
    await page.goto('/o/northwind/metrics')
    await expect(page.getByRole('heading', { name: 'Metrics' })).toBeVisible()
    const results = await new AxeBuilder({ page }).withTags(RULES).analyze()
    expect(results.violations).toEqual([])
  })

  test('settings has no violations', async ({ page }) => {
    await loginSeedUser(page, 'ada@example.com')
    await page.goto('/o/northwind/settings')
    await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible()
    const results = await new AxeBuilder({ page }).withTags(RULES).analyze()
    expect(results.violations).toEqual([])
  })
})
