// Small utility pages: onboarding (create first org), 403, 404.

import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { ApiError, request } from '../api/client'
import type { Data, Org } from '../api/types'
import type { Role } from '../api/types'
import { Button, Field, Spinner } from '../components/ui'
import { useAuth } from '../store/auth'
import { toast } from '../store/ui'

export function OnboardingPage() {
  const navigate = useNavigate()
  const loadSession = useAuth((s) => s.loadSession)
  const setActiveOrg = useAuth((s) => s.setActiveOrg)
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    try {
      const res = await request<Data<Org>>('/api/v1/orgs', {
        method: 'POST',
        body: { name, slug },
      })
      await loadSession()
      setActiveOrg(res.data.slug)
      navigate(`/o/${res.data.slug}/incidents`)
    } catch (err) {
      toast('error', err instanceof ApiError ? err.message : 'Could not create the organisation.')
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1 className="auth-title">Create your organisation</h1>
        <p className="auth-subtitle">You will be its owner. You can invite your team next.</p>
        <form onSubmit={submit}>
          <Field label="Name" htmlFor="org-name">
            <input
              id="org-name"
              value={name}
              onChange={(e) => {
                setName(e.target.value)
                setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''))
              }}
              autoFocus
            />
          </Field>
          <Field label="URL slug" htmlFor="org-slug" hint="Lowercase letters, digits, and hyphens.">
            <input id="org-slug" value={slug} onChange={(e) => setSlug(e.target.value)} />
          </Field>
          <Button type="submit" variant="primary" style={{ width: '100%' }}>
            Create organisation
          </Button>
        </form>
      </div>
    </div>
  )
}

export function AcceptInvitePage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const token = params.get('token')
  const loadSession = useAuth((s) => s.loadSession)
  const setActiveOrg = useAuth((s) => s.setActiveOrg)
  const [state, setState] = useState<'working' | 'error'>('working')

  useEffect(() => {
    async function accept() {
      try {
        const res = await request<Data<{ org_slug: string; org_name: string; role: Role }>>(
          '/api/v1/invitations/accept',
          { method: 'POST', body: { token } },
        )
        await loadSession()
        setActiveOrg(res.data.org_slug)
        toast('success', `You joined ${res.data.org_name}`)
        navigate(`/o/${res.data.org_slug}/incidents`)
      } catch (err) {
        toast('error', err instanceof ApiError ? err.message : 'Could not accept the invitation.')
        setState('error')
      }
    }
    void accept()
  }, [token, loadSession, setActiveOrg, navigate])

  if (state === 'error') {
    return (
      <div className="route-error" role="alert">
        <h1>Invitation problem</h1>
        <p>This invitation is invalid, expired, or was sent to a different address.</p>
        <Link to="/" className="btn btn-secondary">
          Go to your organisations
        </Link>
      </div>
    )
  }
  return (
    <div className="app-loading">
      <Spinner label="Accepting your invitation" />
    </div>
  )
}

export function ForbiddenPage() {
  return (
    <div className="route-error" role="alert">
      <h1>Not allowed</h1>
      <p>Your role in this organisation does not permit this. Ask an admin if you need access.</p>
      <Link to="/" className="btn btn-secondary">
        Back to safety
      </Link>
    </div>
  )
}

export function NotFoundPage() {
  return (
    <div className="route-error" role="alert">
      <h1>Not found</h1>
      <p>There is nothing at this address. It may have been moved or deleted.</p>
      <Link to="/" className="btn btn-secondary">
        Back to safety
      </Link>
    </div>
  )
}
