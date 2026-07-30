// Incident list: virtualised table, saved filter views per user, and full
// keyboard control (j/k to move, Enter to open, / to focus search).

import { useVirtualizer } from '@tanstack/react-virtual'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import type { IncidentStatus, Severity } from '../api/types'
import { useIncidents, type IncidentFilters } from '../api/queries'
import { CreateIncidentDialog } from '../components/CreateIncidentDialog'
import { SeverityBadge, Skeleton, StatusBadge, EmptyState } from '../components/ui'
import { STATUS_LABEL, SEVERITY_LABEL, relativeTime } from '../lib/format'
import { can } from '../lib/permissions'
import { useSavedViews } from '../lib/savedViews'
import { useOrgContext } from '../lib/useOrgContext'
import './incidents.css'

const STATUSES: IncidentStatus[] = ['open', 'acknowledged', 'mitigated', 'resolved', 'postmortem']
const SEVERITIES: Severity[] = ['sev1', 'sev2', 'sev3', 'sev4']

export function IncidentsPage() {
  const { slug, role } = useOrgContext()
  const navigate = useNavigate()
  const searchRef = useRef<HTMLInputElement>(null)
  const parentRef = useRef<HTMLDivElement>(null)

  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<IncidentStatus | ''>('')
  const [severityFilter, setSeverityFilter] = useState<Severity | ''>('')
  const [creating, setCreating] = useState(false)
  const [cursor, setCursor] = useState(0)
  const { views, saveView, applyView } = useSavedViews(slug)

  const filters: IncidentFilters = useMemo(
    () => ({
      q: search || undefined,
      status: statusFilter ? [statusFilter] : undefined,
      severity: severityFilter ? [severityFilter] : undefined,
    }),
    [search, statusFilter, severityFilter],
  )

  const { data, isPending } = useIncidents(slug, filters)
  const incidents = useMemo(() => data?.data ?? [], [data])

  const rowVirtualizer = useVirtualizer({
    count: incidents.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 44,
    overscan: 10,
  })

  useEffect(() => {
    setCursor(0)
  }, [incidents.length])

  // Keyboard navigation: j/k move, Enter opens, / focuses search.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const tag = (e.target as HTMLElement).tagName
      const typing = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'
      if (e.key === '/' && !typing) {
        e.preventDefault()
        searchRef.current?.focus()
        return
      }
      if (typing) return
      if (e.key === 'j') {
        e.preventDefault()
        setCursor((c) => Math.min(c + 1, incidents.length - 1))
      } else if (e.key === 'k') {
        e.preventDefault()
        setCursor((c) => Math.max(c - 1, 0))
      } else if (e.key === 'Enter' && incidents[cursor]) {
        navigate(`/o/${slug}/incidents/${incidents[cursor].id}`)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [incidents, cursor, navigate, slug])

  useEffect(() => {
    if (incidents.length) rowVirtualizer.scrollToIndex(cursor, { align: 'auto' })
  }, [cursor, incidents.length, rowVirtualizer])

  return (
    <div className="incidents">
      <header className="page-head">
        <div>
          <h1>Incidents</h1>
          <p className="page-sub">
            {incidents.length} shown · <kbd>j</kbd>/<kbd>k</kbd> to move, <kbd>Enter</kbd> to open,{' '}
            <kbd>/</kbd> to search
          </p>
        </div>
        {can(role, 'incident:create') ? (
          <button className="btn btn-primary" onClick={() => setCreating(true)}>
            Report incident
          </button>
        ) : null}
      </header>

      <div className="filters">
        <input
          ref={searchRef}
          type="search"
          placeholder="Search title and description…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label="Search incidents"
        />
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as IncidentStatus | '')}
          aria-label="Filter by status"
        >
          <option value="">All statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {STATUS_LABEL[s]}
            </option>
          ))}
        </select>
        <select
          value={severityFilter}
          onChange={(e) => setSeverityFilter(e.target.value as Severity | '')}
          aria-label="Filter by severity"
        >
          <option value="">All severities</option>
          {SEVERITIES.map((s) => (
            <option key={s} value={s}>
              {SEVERITY_LABEL[s]}
            </option>
          ))}
        </select>
        <button
          className="btn btn-ghost"
          onClick={() => saveView({ q: search, status: statusFilter, severity: severityFilter })}
        >
          Save view
        </button>
      </div>

      {views.length > 0 ? (
        <div className="saved-views" aria-label="Saved views">
          {views.map((v, i) => (
            <button
              key={i}
              className="chip"
              onClick={() => {
                const applied = applyView(v)
                setSearch(applied.q)
                setStatusFilter(applied.status)
                setSeverityFilter(applied.severity)
              }}
            >
              {v.name}
            </button>
          ))}
        </div>
      ) : null}

      {isPending ? (
        <Skeleton rows={8} />
      ) : incidents.length === 0 ? (
        <EmptyState title="No incidents match">
          Adjust the filters, or report the first incident with the button above.
        </EmptyState>
      ) : (
        <div className="table">
          <div className="thead" aria-hidden>
            <span>#</span>
            <span>Severity</span>
            <span>Title</span>
            <span>Status</span>
            <span>Started</span>
          </div>
          <div ref={parentRef} className="tbody">
            <ul
              className="trow-list"
              style={{ height: rowVirtualizer.getTotalSize(), position: 'relative' }}
              aria-label="Incidents"
            >
              {rowVirtualizer.getVirtualItems().map((vi) => {
                const incident = incidents[vi.index]
                if (!incident) return null
                return (
                  <li key={incident.id} style={{ transform: `translateY(${vi.start}px)` }} className="trow-li">
                    <button
                      className={`trow ${vi.index === cursor ? 'trow-cursor' : ''}`}
                      onClick={() => navigate(`/o/${slug}/incidents/${incident.id}`)}
                      onMouseEnter={() => setCursor(vi.index)}
                      aria-label={`${incident.number}, severity ${incident.severity}, ${incident.status}: ${incident.title}`}
                    >
                      <span className="mono cell-num">{incident.number}</span>
                      <span>
                        <SeverityBadge severity={incident.severity} />
                      </span>
                      <span className="cell-title">{incident.title}</span>
                      <span>
                        <StatusBadge status={incident.status} />
                      </span>
                      <span className="cell-time">{relativeTime(incident.started_at)}</span>
                    </button>
                  </li>
                )
              })}
            </ul>
          </div>
        </div>
      )}

      {creating ? <CreateIncidentDialog org={slug} onClose={() => setCreating(false)} /> : null}
    </div>
  )
}
