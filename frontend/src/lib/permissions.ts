// The permission matrix, mirrored from the backend (authz.py). The UI uses it
// to hide controls a role cannot use; the backend enforces it for real, so
// this is a usability layer, never the security boundary.

import type { Role } from '../api/types'

export type Permission =
  | 'org:view'
  | 'org:manage'
  | 'member:view'
  | 'member:manage'
  | 'service:view'
  | 'service:manage'
  | 'incident:view'
  | 'incident:create'
  | 'incident:update'
  | 'comment:create'
  | 'comment:moderate'
  | 'attachment:upload'
  | 'oncall:view'
  | 'oncall:manage'
  | 'audit:view'
  | 'apikey:manage'
  | 'metrics:view'

const VIEWER: Permission[] = [
  'org:view',
  'member:view',
  'service:view',
  'incident:view',
  'oncall:view',
  'metrics:view',
]

const RESPONDER: Permission[] = [
  ...VIEWER,
  'incident:create',
  'incident:update',
  'comment:create',
  'attachment:upload',
]

const ADMIN: Permission[] = [
  ...RESPONDER,
  'member:manage',
  'service:manage',
  'oncall:manage',
  'comment:moderate',
  'audit:view',
  'apikey:manage',
]

const OWNER: Permission[] = [...ADMIN, 'org:manage']

const MATRIX: Record<Role, ReadonlySet<Permission>> = {
  viewer: new Set(VIEWER),
  responder: new Set(RESPONDER),
  admin: new Set(ADMIN),
  owner: new Set(OWNER),
}

export function can(role: Role | null | undefined, permission: Permission): boolean {
  if (!role) return false
  return MATRIX[role].has(permission)
}

export const ALL_PERMISSIONS: Permission[] = [...OWNER].sort()
