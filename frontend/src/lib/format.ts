// Small pure formatting helpers, unit-tested.

import type { IncidentStatus, Severity } from '../api/types'

export const SEVERITY_LABEL: Record<Severity, string> = {
  sev1: 'SEV1',
  sev2: 'SEV2',
  sev3: 'SEV3',
  sev4: 'SEV4',
}

export const STATUS_LABEL: Record<IncidentStatus, string> = {
  open: 'Open',
  acknowledged: 'Acknowledged',
  mitigated: 'Mitigated',
  resolved: 'Resolved',
  postmortem: 'Postmortem',
}

// Legal state-machine transitions, mirrored from the backend so the UI only
// ever offers moves the server will accept.
export const LEGAL_TRANSITIONS: Record<IncidentStatus, IncidentStatus[]> = {
  open: ['acknowledged'],
  acknowledged: ['mitigated', 'resolved'],
  mitigated: ['resolved'],
  resolved: ['postmortem'],
  postmortem: [],
}

export function formatDuration(seconds: number | null): string {
  if (seconds === null) return 'n/a'
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h`
  return `${(seconds / 86400).toFixed(1)}d`
}

export function relativeTime(iso: string, now: Date = new Date()): string {
  const then = new Date(iso).getTime()
  const diff = Math.round((now.getTime() - then) / 1000)
  if (diff < 45) return 'just now'
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`
  return `${Math.round(diff / 86400)}d ago`
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
