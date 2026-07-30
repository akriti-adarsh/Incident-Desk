// Saved filter views, persisted per user+org in localStorage.

import { useCallback, useState } from 'react'

import type { IncidentStatus, Severity } from '../api/types'

export interface SavedView {
  name: string
  q: string
  status: IncidentStatus | ''
  severity: Severity | ''
}

function storageKey(org: string): string {
  return `incident_desk.views.${org}`
}

function load(org: string): SavedView[] {
  try {
    const raw = localStorage.getItem(storageKey(org))
    return raw ? (JSON.parse(raw) as SavedView[]) : []
  } catch {
    return []
  }
}

export function useSavedViews(org: string) {
  const [views, setViews] = useState<SavedView[]>(() => load(org))

  const saveView = useCallback(
    (filters: Omit<SavedView, 'name'>) => {
      const parts = [
        filters.q && `"${filters.q}"`,
        filters.status || null,
        filters.severity || null,
      ].filter(Boolean)
      const name = parts.length ? parts.join(' · ') : 'All incidents'
      setViews((prev) => {
        const next = [{ name, ...filters }, ...prev.filter((v) => v.name !== name)].slice(0, 6)
        localStorage.setItem(storageKey(org), JSON.stringify(next))
        return next
      })
    },
    [org],
  )

  const applyView = useCallback((view: SavedView) => view, [])

  return { views, saveView, applyView }
}
