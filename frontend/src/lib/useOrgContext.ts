import { useParams } from 'react-router-dom'

import type { Role } from '../api/types'
import { useAuth } from '../store/auth'

export interface OrgContext {
  slug: string
  role: Role | null
}

// The active org for the current route, plus the caller's role in it (for UI
// gating). Falls back to the auth store's active org when the route has none.
export function useOrgContext(): OrgContext {
  const { orgSlug } = useParams<{ orgSlug: string }>()
  const orgs = useAuth((s) => s.orgs)
  const activeOrgSlug = useAuth((s) => s.activeOrgSlug)
  const slug = orgSlug ?? activeOrgSlug ?? ''
  const role = orgs.find((o) => o.slug === slug)?.role ?? null
  return { slug, role }
}
