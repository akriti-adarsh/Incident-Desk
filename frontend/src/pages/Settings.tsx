// Settings: members and roles, services, API keys, and the audit-log viewer.
// Each section is role-gated; controls a role cannot use are not rendered.

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { ApiError, request } from '../api/client'
import type { ApiKeyCreated, Data, Role } from '../api/types'
import {
  keys,
  useApiKeys,
  useAuditLog,
  useMembers,
  useServices,
} from '../api/queries'
import { Modal } from '../components/Modal'
import { Button, Field } from '../components/ui'
import { ALL_PERMISSIONS, can } from '../lib/permissions'
import { relativeTime } from '../lib/format'
import { useOrgContext } from '../lib/useOrgContext'
import { toast } from '../store/ui'
import './settings.css'

const TABS = ['Members', 'Services', 'API keys', 'Audit log'] as const
type Tab = (typeof TABS)[number]
const ROLES: Role[] = ['owner', 'admin', 'responder', 'viewer']

export function SettingsPage() {
  const { role } = useOrgContext()
  const [tab, setTab] = useState<Tab>('Members')
  const visible = TABS.filter((t) => {
    if (t === 'API keys') return can(role, 'apikey:manage')
    if (t === 'Audit log') return can(role, 'audit:view')
    return true
  })

  return (
    <div className="settings">
      <h1>Settings</h1>
      <div className="tabs" role="tablist">
        {visible.map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            className={`tab ${tab === t ? 'tab-active' : ''}`}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </div>
      <div className="tab-panel" role="tabpanel">
        {tab === 'Members' && <MembersTab />}
        {tab === 'Services' && <ServicesTab />}
        {tab === 'API keys' && <ApiKeysTab />}
        {tab === 'Audit log' && <AuditTab />}
      </div>
    </div>
  )
}

function MembersTab() {
  const { slug, role } = useOrgContext()
  const qc = useQueryClient()
  const members = useMembers(slug)
  const [inviteOpen, setInviteOpen] = useState(false)
  const canManage = can(role, 'member:manage')

  const changeRole = useMutation({
    mutationFn: ({ userId, newRole }: { userId: string; newRole: Role }) =>
      request(`/api/v1/orgs/${slug}/members/${userId}`, {
        method: 'PATCH',
        body: { role: newRole },
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.members(slug) }),
    onError: (err) => toast('error', err instanceof ApiError ? err.message : 'Could not change the role.'),
  })

  const remove = useMutation({
    mutationFn: (userId: string) =>
      request(`/api/v1/orgs/${slug}/members/${userId}`, { method: 'DELETE' }),
    onSuccess: () => {
      toast('success', 'Member removed')
      qc.invalidateQueries({ queryKey: keys.members(slug) })
    },
    onError: (err) => toast('error', err instanceof ApiError ? err.message : 'Could not remove the member.'),
  })

  return (
    <div>
      <div className="section-head">
        <h2>Members</h2>
        {canManage ? (
          <Button variant="primary" onClick={() => setInviteOpen(true)}>
            Invite someone
          </Button>
        ) : null}
      </div>
      <table className="data-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Email</th>
            <th>Role</th>
            {canManage ? <th aria-label="Actions" /> : null}
          </tr>
        </thead>
        <tbody>
          {(members.data?.data ?? []).map((m) => (
            <tr key={m.user_id}>
              <td>{m.full_name}</td>
              <td className="cell-muted">{m.email}</td>
              <td>
                {canManage ? (
                  <select
                    value={m.role}
                    onChange={(e) => changeRole.mutate({ userId: m.user_id, newRole: e.target.value as Role })}
                    aria-label={`Role for ${m.full_name}`}
                    style={{ width: 'auto' }}
                  >
                    {ROLES.map((r) => (
                      <option key={r} value={r}>
                        {r}
                      </option>
                    ))}
                  </select>
                ) : (
                  m.role
                )}
              </td>
              {canManage ? (
                <td>
                  <button className="link-btn danger-link" onClick={() => remove.mutate(m.user_id)}>
                    Remove
                  </button>
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
      {inviteOpen ? <InviteDialog org={slug} onClose={() => setInviteOpen(false)} /> : null}
    </div>
  )
}

function InviteDialog({ org, onClose }: { org: string; onClose: () => void }) {
  const qc = useQueryClient()
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<Role>('responder')
  async function submit(e: React.FormEvent) {
    e.preventDefault()
    try {
      await request(`/api/v1/orgs/${org}/invitations`, {
        method: 'POST',
        body: { email, role },
      })
      toast('success', `Invitation sent to ${email}`)
      qc.invalidateQueries({ queryKey: keys.members(org) })
      onClose()
    } catch (err) {
      toast('error', err instanceof ApiError ? err.message : 'Could not send the invitation.')
    }
  }
  return (
    <Modal title="Invite someone" onClose={onClose}>
      <form onSubmit={submit}>
        <Field label="Email" htmlFor="invite-email">
          <input id="invite-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
        </Field>
        <Field label="Role" htmlFor="invite-role">
          <select id="invite-role" value={role} onChange={(e) => setRole(e.target.value as Role)}>
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </Field>
        <div className="modal-actions">
          <Button type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary">
            Send invitation
          </Button>
        </div>
      </form>
    </Modal>
  )
}

function ServicesTab() {
  const { slug, role } = useOrgContext()
  const qc = useQueryClient()
  const services = useServices(slug)
  const canManage = can(role, 'service:manage')
  const [name, setName] = useState('')

  const create = useMutation({
    mutationFn: () => request(`/api/v1/orgs/${slug}/services`, { method: 'POST', body: { name } }),
    onSuccess: () => {
      setName('')
      qc.invalidateQueries({ queryKey: keys.services(slug) })
    },
    onError: (err) => toast('error', err instanceof ApiError ? err.message : 'Could not create the service.'),
  })

  return (
    <div>
      <h2>Services</h2>
      {canManage ? (
        <form
          className="inline-form"
          onSubmit={(e) => {
            e.preventDefault()
            if (name.trim()) create.mutate()
          }}
        >
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="New service name" aria-label="New service name" />
          <Button type="submit" variant="primary" disabled={!name.trim()}>
            Add service
          </Button>
        </form>
      ) : null}
      <table className="data-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Tier</th>
            <th>Owner team</th>
          </tr>
        </thead>
        <tbody>
          {(services.data?.data ?? []).map((s) => (
            <tr key={s.id}>
              <td>{s.name}</td>
              <td>{s.tier}</td>
              <td className="cell-muted">{s.owner_team || 'n/a'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ApiKeysTab() {
  const { slug } = useOrgContext()
  const qc = useQueryClient()
  const apiKeys = useApiKeys(slug)
  const [createdToken, setCreatedToken] = useState<string | null>(null)
  const [name, setName] = useState('')

  const create = useMutation({
    mutationFn: () =>
      request<Data<ApiKeyCreated>>(`/api/v1/orgs/${slug}/api-keys`, {
        method: 'POST',
        body: { name, scopes: ['incident:view', 'incident:create'] },
      }),
    onSuccess: (res) => {
      setCreatedToken(res.data.api_key)
      setName('')
      qc.invalidateQueries({ queryKey: keys.apiKeys(slug) })
    },
    onError: (err) => toast('error', err instanceof ApiError ? err.message : 'Could not create the key.'),
  })

  const revoke = useMutation({
    mutationFn: (id: string) => request(`/api/v1/orgs/${slug}/api-keys/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      toast('success', 'API key revoked')
      qc.invalidateQueries({ queryKey: keys.apiKeys(slug) })
    },
  })

  return (
    <div>
      <h2>API keys</h2>
      <p className="rail-muted">Keys read and create incidents with the incident:view and incident:create scopes.</p>
      <form
        className="inline-form"
        onSubmit={(e) => {
          e.preventDefault()
          if (name.trim()) create.mutate()
        }}
      >
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Key name (e.g. ci-bot)" aria-label="Key name" />
        <Button type="submit" variant="primary" disabled={!name.trim()}>
          Create key
        </Button>
      </form>
      <table className="data-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Prefix</th>
            <th>Last used</th>
            <th>Status</th>
            <th aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          {(apiKeys.data?.data ?? []).map((k) => (
            <tr key={k.id}>
              <td>{k.name}</td>
              <td className="mono">{k.prefix}</td>
              <td className="cell-muted">{k.last_used_at ? relativeTime(k.last_used_at) : 'never'}</td>
              <td>{k.revoked_at ? 'revoked' : 'active'}</td>
              <td>
                {!k.revoked_at ? (
                  <button className="link-btn danger-link" onClick={() => revoke.mutate(k.id)}>
                    Revoke
                  </button>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {createdToken ? (
        <Modal title="Copy your API key" onClose={() => setCreatedToken(null)}>
          <p className="rail-muted">This is the only time the key is shown. Store it now.</p>
          <pre className="token-box">{createdToken}</pre>
          <div className="modal-actions">
            <Button
              variant="primary"
              onClick={() => {
                void navigator.clipboard?.writeText(createdToken)
                toast('success', 'Copied to clipboard')
              }}
            >
              Copy
            </Button>
          </div>
        </Modal>
      ) : null}
      <p className="rail-muted mono-hint">Scopes available: {ALL_PERMISSIONS.length} permissions.</p>
    </div>
  )
}

function AuditTab() {
  const { slug } = useOrgContext()
  const audit = useAuditLog(slug)
  return (
    <div>
      <h2>Audit log</h2>
      <table className="data-table">
        <thead>
          <tr>
            <th>When</th>
            <th>Action</th>
            <th>Resource</th>
          </tr>
        </thead>
        <tbody>
          {(audit.data?.data ?? []).map((e) => (
            <tr key={e.id}>
              <td className="cell-muted">{relativeTime(e.created_at)}</td>
              <td className="mono">{e.action}</td>
              <td className="cell-muted">{e.resource_type}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
