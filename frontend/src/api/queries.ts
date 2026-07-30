// Query-key factories and typed hooks over the API client. WebSocket events
// invalidate precise keys (see useRealtime), never a blanket invalidate.

import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query'

import { request, requestResponse } from './client'
import type {
  ApiKey,
  Attachment,
  AuditEntry,
  Comment,
  Data,
  Incident,
  IncidentStatus,
  Member,
  MetricsSummary,
  OnCallNow,
  Page,
  Schedule,
  Service,
  Severity,
  Shift,
  TimelineEvent,
} from './types'

export const keys = {
  incidents: (org: string, filters?: Record<string, unknown>) =>
    ['incidents', org, filters ?? {}] as const,
  incident: (org: string, id: string) => ['incident', org, id] as const,
  events: (org: string, id: string) => ['events', org, id] as const,
  comments: (org: string, id: string) => ['comments', org, id] as const,
  attachments: (org: string, id: string) => ['attachments', org, id] as const,
  services: (org: string) => ['services', org] as const,
  members: (org: string) => ['members', org] as const,
  invitations: (org: string) => ['invitations', org] as const,
  schedules: (org: string) => ['schedules', org] as const,
  shifts: (org: string, scheduleId: string) => ['shifts', org, scheduleId] as const,
  whoIsOnCall: (org: string, serviceId: string) => ['who-on-call', org, serviceId] as const,
  apiKeys: (org: string) => ['api-keys', org] as const,
  audit: (org: string, filters?: Record<string, unknown>) =>
    ['audit', org, filters ?? {}] as const,
  metrics: (org: string) => ['metrics', org] as const,
}

export interface IncidentFilters {
  status?: IncidentStatus[]
  severity?: Severity[]
  service_id?: string
  assigned_to?: string
  tag?: string
  q?: string
  sort?: string
  [key: string]: string | number | string[] | undefined
}

export function useIncidents(org: string, filters: IncidentFilters = {}) {
  return useQuery({
    queryKey: keys.incidents(org, filters),
    queryFn: ({ signal }) =>
      request<Page<Incident>>(`/api/v1/orgs/${org}/incidents`, {
        query: { ...filters, limit: 50 },
        signal,
      }),
    staleTime: 10_000,
  })
}

export function useIncident(org: string, id: string) {
  return useQuery({
    queryKey: keys.incident(org, id),
    queryFn: ({ signal }) =>
      request<Data<Incident>>(`/api/v1/orgs/${org}/incidents/${id}`, { signal }),
    staleTime: 5_000,
  })
}

export function useTimeline(org: string, id: string) {
  return useQuery({
    queryKey: keys.events(org, id),
    queryFn: ({ signal }) =>
      request<Page<TimelineEvent>>(`/api/v1/orgs/${org}/incidents/${id}/events`, {
        query: { limit: 200 },
        signal,
      }),
    staleTime: 5_000,
  })
}

export function useComments(org: string, id: string) {
  return useQuery({
    queryKey: keys.comments(org, id),
    queryFn: ({ signal }) =>
      request<Page<Comment>>(`/api/v1/orgs/${org}/incidents/${id}/comments`, {
        query: { limit: 200 },
        signal,
      }),
    staleTime: 5_000,
  })
}

export function useAttachmentsQuery(org: string, id: string) {
  return useQuery({
    queryKey: keys.attachments(org, id),
    queryFn: ({ signal }) =>
      request<Data<Attachment[]>>(`/api/v1/orgs/${org}/incidents/${id}/attachments`, { signal }),
    staleTime: 10_000,
  })
}

export function useServices(org: string) {
  return useQuery({
    queryKey: keys.services(org),
    queryFn: ({ signal }) =>
      request<Data<Service[]>>(`/api/v1/orgs/${org}/services`, { signal }),
    staleTime: 60_000,
  })
}

export function useMembers(org: string) {
  return useQuery({
    queryKey: keys.members(org),
    queryFn: ({ signal }) =>
      request<Data<Member[]>>(`/api/v1/orgs/${org}/members`, { signal }),
    staleTime: 30_000,
  })
}

export function useSchedules(org: string) {
  return useQuery({
    queryKey: keys.schedules(org),
    queryFn: ({ signal }) =>
      request<Data<Schedule[]>>(`/api/v1/orgs/${org}/on-call/schedules`, { signal }),
    staleTime: 60_000,
  })
}

export function useShifts(org: string, scheduleId: string, from?: string, to?: string) {
  return useQuery({
    queryKey: keys.shifts(org, scheduleId),
    queryFn: ({ signal }) =>
      request<Data<Shift[]>>(
        `/api/v1/orgs/${org}/on-call/schedules/${scheduleId}/shifts`,
        { query: { from, to }, signal },
      ),
    staleTime: 60_000,
  })
}

export function useWhoIsOnCall(org: string, serviceId: string | undefined) {
  return useQuery({
    queryKey: keys.whoIsOnCall(org, serviceId ?? ''),
    enabled: Boolean(serviceId),
    queryFn: ({ signal }) =>
      request<Data<OnCallNow[]>>(`/api/v1/orgs/${org}/on-call/who-is-on-call`, {
        query: { service_id: serviceId },
        signal,
      }),
    staleTime: 30_000,
  })
}

export function useApiKeys(org: string) {
  return useQuery({
    queryKey: keys.apiKeys(org),
    queryFn: ({ signal }) =>
      request<Data<ApiKey[]>>(`/api/v1/orgs/${org}/api-keys`, { signal }),
    staleTime: 30_000,
  })
}

export function useAuditLog(org: string, filters: Record<string, string> = {}) {
  return useQuery({
    queryKey: keys.audit(org, filters),
    queryFn: ({ signal }) =>
      request<Page<AuditEntry>>(`/api/v1/orgs/${org}/audit-log`, {
        query: { ...filters, limit: 100 },
        signal,
      }),
    staleTime: 15_000,
  })
}

export function useMetrics(org: string) {
  return useQuery({
    queryKey: keys.metrics(org),
    queryFn: ({ signal }) =>
      request<Data<MetricsSummary>>(`/api/v1/orgs/${org}/metrics/summary`, { signal }),
    staleTime: 60_000,
  })
}

// Mutations

export function useCreateIncident(org: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      service_id: string
      title: string
      description?: string
      severity: Severity
      assigned_to?: string | null
      tags?: string[]
    }) =>
      request<Data<Incident>>(`/api/v1/orgs/${org}/incidents`, {
        method: 'POST',
        body,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['incidents', org] })
    },
  })
}

export function useChangeStatus(org: string, id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { status: IncidentStatus; resolution_summary?: string }) =>
      request<Data<Incident>>(`/api/v1/orgs/${org}/incidents/${id}/status`, {
        method: 'POST',
        body,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.incident(org, id) })
      qc.invalidateQueries({ queryKey: keys.events(org, id) })
      qc.invalidateQueries({ queryKey: ['incidents', org] })
    },
  })
}

export function useUpdateIncident(org: string, id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ version, ...body }: Partial<Incident> & { version: number }) =>
      request<Data<Incident>>(`/api/v1/orgs/${org}/incidents/${id}`, {
        method: 'PATCH',
        headers: { 'If-Match': `"${version}"` },
        body,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.incident(org, id) })
      qc.invalidateQueries({ queryKey: keys.events(org, id) })
    },
  })
}

export function invalidateIncidentKeys(
  qc: QueryClient,
  org: string,
  incidentId?: string,
): void {
  qc.invalidateQueries({ queryKey: ['incidents', org] })
  if (incidentId) {
    qc.invalidateQueries({ queryKey: keys.incident(org, incidentId) })
    qc.invalidateQueries({ queryKey: keys.events(org, incidentId) })
    qc.invalidateQueries({ queryKey: keys.comments(org, incidentId) })
  }
}

export async function uploadAttachment(
  org: string,
  incidentId: string,
  file: File,
): Promise<void> {
  const form = new FormData()
  form.append('file', file)
  await requestResponse(`/api/v1/orgs/${org}/incidents/${incidentId}/attachments`, {
    method: 'POST',
    body: form,
  })
}
