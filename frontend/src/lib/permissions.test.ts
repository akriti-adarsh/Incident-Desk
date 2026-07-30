import { describe, expect, it } from 'vitest'

import type { Role } from '../api/types'
import { ALL_PERMISSIONS, can, type Permission } from './permissions'

// Mirror of the backend truth table; the two must agree or the UI gates the
// wrong controls. This is the client-side counterpart of the backend's
// exhaustive matrix test.
const EXPECTED: Record<Role, Permission[]> = {
  viewer: ['org:view', 'member:view', 'service:view', 'incident:view', 'oncall:view', 'metrics:view'],
  responder: [
    'org:view', 'member:view', 'service:view', 'incident:view', 'oncall:view', 'metrics:view',
    'incident:create', 'incident:update', 'comment:create', 'attachment:upload',
  ],
  admin: [
    'org:view', 'member:view', 'service:view', 'incident:view', 'oncall:view', 'metrics:view',
    'incident:create', 'incident:update', 'comment:create', 'attachment:upload',
    'member:manage', 'service:manage', 'oncall:manage', 'comment:moderate', 'audit:view', 'apikey:manage',
  ],
  owner: [...ALL_PERMISSIONS],
}

const ROLES: Role[] = ['viewer', 'responder', 'admin', 'owner']

describe('permission matrix', () => {
  it.each(ROLES)('%s has exactly its expected permissions', (role) => {
    for (const permission of ALL_PERMISSIONS) {
      expect(can(role, permission)).toBe(EXPECTED[role].includes(permission))
    }
  })

  it('grants nothing to a missing role', () => {
    expect(can(null, 'incident:view')).toBe(false)
    expect(can(undefined, 'org:view')).toBe(false)
  })

  it('escalates monotonically', () => {
    expect(EXPECTED.viewer.every((p) => EXPECTED.responder.includes(p))).toBe(true)
    expect(EXPECTED.responder.every((p) => EXPECTED.admin.includes(p))).toBe(true)
    expect(EXPECTED.admin.every((p) => EXPECTED.owner.includes(p))).toBe(true)
  })

  it('only the owner can manage the org', () => {
    expect(can('owner', 'org:manage')).toBe(true)
    expect(can('admin', 'org:manage')).toBe(false)
  })
})
