// Wraps every org-scoped route: subscribes to the org's incident stream (so
// lists/details stay live across replicas) and renders the layout outlet.

import { useEffect } from 'react'
import { Navigate, useParams } from 'react-router-dom'

import { Layout } from '../components/Layout'
import { useOrgIncidentStream } from '../lib/useRealtime'
import { useAuth } from '../store/auth'

export function OrgRoutes() {
  const { orgSlug } = useParams<{ orgSlug: string }>()
  const orgs = useAuth((s) => s.orgs)
  const setActiveOrg = useAuth((s) => s.setActiveOrg)
  const known = orgs.some((o) => o.slug === orgSlug)

  useEffect(() => {
    if (orgSlug && known) setActiveOrg(orgSlug)
  }, [orgSlug, known, setActiveOrg])

  useOrgIncidentStream(known ? (orgSlug ?? '') : '')

  if (!known) {
    return <Navigate to={orgs[0] ? `/o/${orgs[0].slug}/incidents` : '/onboarding'} replace />
  }
  return <Layout />
}
