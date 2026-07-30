import { expect, test } from '@playwright/test'

import { login, SEED_PASSWORD, tokenFromEmail, uniqueEmail } from './helpers'

// The full lifecycle: register -> verify -> create org -> invite a second user
// -> second user accepts -> create incident -> acknowledge -> comment -> assign
// -> resolve -> verify the audit log recorded it.
test('full incident lifecycle across two users', async ({ page, request, browser }) => {
  const ownerEmail = uniqueEmail('owner')
  const inviteeEmail = uniqueEmail('invitee')

  // Register the owner and verify their email.
  await page.goto('/register')
  await page.getByLabel('Full name').fill('E2E Owner')
  await page.getByLabel('Email').fill(ownerEmail)
  await page.getByLabel('Password').fill(SEED_PASSWORD)
  await page.getByRole('button', { name: 'Create account' }).click()
  await expect(page.getByRole('heading', { name: 'Check your email' })).toBeVisible()

  const verifyToken = await tokenFromEmail(request, ownerEmail, 'verify-email')
  await page.goto(`/verify-email?token=${verifyToken}`)
  await page.getByRole('button', { name: 'Verify email' }).click()
  await expect(page.getByText('Your email is verified')).toBeVisible()

  // Log in and create an organisation.
  await login(page, ownerEmail)
  await expect(page.getByRole('heading', { name: 'Create your organisation' })).toBeVisible()
  const slug = `e2e-${Date.now()}`
  await page.getByLabel('Name').fill('E2E Org')
  await page.getByLabel('URL slug').fill(slug)
  await page.getByRole('button', { name: 'Create organisation' }).click()
  await expect(page.getByRole('heading', { name: 'Incidents' })).toBeVisible()

  // A service is needed to report an incident; create one in settings.
  await page.goto(`/o/${slug}/settings`)
  await page.getByRole('tab', { name: 'Services' }).click()
  await page.getByPlaceholder('New service name').fill('payments-api')
  await page.getByRole('button', { name: 'Add service' }).click()
  await expect(page.getByRole('cell', { name: 'payments-api' })).toBeVisible()

  // Invite a second user as a responder.
  await page.getByRole('tab', { name: 'Members' }).click()
  await page.getByRole('button', { name: 'Invite someone' }).click()
  const inviteDialog = page.getByRole('dialog', { name: 'Invite someone' })
  await inviteDialog.getByLabel('Email').fill(inviteeEmail)
  await inviteDialog.getByLabel('Role').selectOption('responder')
  await inviteDialog.getByRole('button', { name: 'Send invitation' }).click()
  const inviteToken = await tokenFromEmail(request, inviteeEmail, 'accept-invite')

  // The invitee registers, verifies, logs in, and accepts, in a second context.
  const inviteeCtx = await browser.newContext()
  const inviteePage = await inviteeCtx.newPage()
  await inviteePage.goto('/register')
  await inviteePage.getByLabel('Full name').fill('E2E Invitee')
  await inviteePage.getByLabel('Email').fill(inviteeEmail)
  await inviteePage.getByLabel('Password').fill(SEED_PASSWORD)
  await inviteePage.getByRole('button', { name: 'Create account' }).click()
  const inviteeVerify = await tokenFromEmail(request, inviteeEmail, 'verify-email')
  await inviteePage.goto(`/verify-email?token=${inviteeVerify}`)
  await inviteePage.getByRole('button', { name: 'Verify email' }).click()
  await expect(inviteePage.getByText('Your email is verified')).toBeVisible()
  await login(inviteePage, inviteeEmail)
  // The invitee has no org yet, so login lands on onboarding; wait for that so
  // the session (access token) is established before accepting the invite.
  await expect(
    inviteePage.getByRole('heading', { name: 'Create your organisation' }),
  ).toBeVisible()
  await inviteePage.goto(`/accept-invite?token=${inviteToken}`)
  await expect(inviteePage.getByRole('heading', { name: 'Incidents' })).toBeVisible()

  // Owner reports an incident.
  await page.goto(`/o/${slug}/incidents`)
  await page.getByRole('button', { name: 'Report incident' }).click()
  const reportDialog = page.getByRole('dialog', { name: 'Report an incident' })
  await reportDialog.getByLabel('Service').selectOption({ label: 'payments-api' })
  await reportDialog.getByLabel('Title').fill('Checkout latency spike')
  await reportDialog.getByLabel('Severity').selectOption('sev1')
  await reportDialog.getByRole('button', { name: 'Report incident' }).click()

  await expect(page.getByRole('heading', { name: 'Checkout latency spike' })).toBeVisible()

  // Acknowledge, comment, then resolve.
  await page.getByRole('button', { name: 'Acknowledged' }).click()
  await expect(page.getByText('Status: open to acknowledged')).toBeVisible()

  await page.getByLabel('Add a comment').fill('Investigating the deploy.')
  await page.getByRole('button', { name: 'Comment', exact: true }).click()
  await expect(page.getByText('Investigating the deploy.')).toBeVisible()

  await page.getByRole('button', { name: 'Resolve incident' }).click()
  const dialog = page.getByRole('dialog', { name: 'Resolve incident' })
  await dialog.getByLabel('Resolution summary').fill('Rolled back the bad deploy.')
  await dialog.getByRole('button', { name: 'Resolve incident' }).click()
  await expect(page.getByText('Status: acknowledged to resolved')).toBeVisible()

  // The audit log recorded the creation.
  await page.goto(`/o/${slug}/settings`)
  await page.getByRole('tab', { name: 'Audit log' }).click()
  await expect(page.getByRole('cell', { name: 'incident.created' }).first()).toBeVisible()

  await inviteeCtx.close()
})
