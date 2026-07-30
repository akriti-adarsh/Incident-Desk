import { describe, expect, it } from 'vitest'

import type { OrgWithRole } from '../api/types'
import { activeOrg } from './auth'

describe('activeOrg selector', () => {
  const orgs: OrgWithRole[] = [
    { id: '1', name: 'A', slug: 'a', plan: 'free', settings: {}, created_at: '', role: 'owner' },
    { id: '2', name: 'B', slug: 'b', plan: 'free', settings: {}, created_at: '', role: 'viewer' },
  ]

  it('resolves the active org and its role', () => {
    expect(activeOrg({ orgs, activeOrgSlug: 'b' } as never)?.role).toBe('viewer')
    expect(activeOrg({ orgs, activeOrgSlug: 'a' } as never)?.role).toBe('owner')
  })

  it('returns null when nothing matches', () => {
    expect(activeOrg({ orgs, activeOrgSlug: 'zzz' } as never)).toBeNull()
  })
})
