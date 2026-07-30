// Domain types mirroring the backend Pydantic schemas. A field rename on the
// backend surfaces here as a type error at the call sites (the openapi drift
// check in CI guards the shapes themselves).

export type Role = 'owner' | 'admin' | 'responder' | 'viewer'
export type ServiceTier = 'tier1' | 'tier2' | 'tier3'
export type Severity = 'sev1' | 'sev2' | 'sev3' | 'sev4'
export type IncidentStatus =
  | 'open'
  | 'acknowledged'
  | 'mitigated'
  | 'resolved'
  | 'postmortem'

export interface ApiErrorBody {
  error: {
    code: string
    message: string
    details?: unknown
    request_id: string
  }
}

export interface Data<T> {
  data: T
}

export interface Page<T> {
  data: T[]
  next_cursor: string | null
}

export interface User {
  id: string
  email: string
  full_name: string
  avatar_url: string | null
  email_verified_at: string | null
  created_at: string
}

export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export interface MfaRequired {
  mfa_required: true
  mfa_token: string
}

export type LoginResult = TokenPair | MfaRequired

export interface Org {
  id: string
  name: string
  slug: string
  plan: string
  settings: Record<string, unknown>
  created_at: string
}

export interface OrgWithRole extends Org {
  role: Role
}

export interface Member {
  user_id: string
  email: string
  full_name: string
  avatar_url: string | null
  role: Role
  joined_at: string
}

export interface Invitation {
  id: string
  email: string
  role: Role
  expires_at: string
  created_at: string
}

export interface Service {
  id: string
  name: string
  description: string
  owner_team: string
  tier: ServiceTier
  created_at: string
  updated_at: string
}

export interface Incident {
  id: string
  number: string
  sequence_number: number
  service_id: string
  title: string
  description: string
  severity: Severity
  status: IncidentStatus
  reported_by: string
  assigned_to: string | null
  started_at: string
  acknowledged_at: string | null
  resolved_at: string | null
  resolution_summary: string | null
  tags: string[]
  version: number
  created_at: string
  updated_at: string
}

export interface TimelineEvent {
  id: string
  event_type: string
  actor_id: string | null
  payload: Record<string, unknown>
  created_at: string
}

export interface Comment {
  id: string
  author_id: string
  body: string
  edited_at: string | null
  created_at: string
}

export interface Attachment {
  id: string
  filename: string
  content_type: string
  size_bytes: number
  checksum: string
  uploader_id: string
  created_at: string
}

export interface Schedule {
  id: string
  service_id: string
  name: string
  rotation: Record<string, unknown>
  created_at: string
}

export interface Shift {
  id: string
  schedule_id: string
  user_id: string
  starts_at: string
  ends_at: string
}

export interface OnCallNow {
  schedule_id: string
  schedule_name: string
  on_call: { user_id: string; full_name: string; email: string } | null
}

export interface ApiKey {
  id: string
  name: string
  prefix: string
  scopes: string[]
  last_used_at: string | null
  expires_at: string | null
  revoked_at: string | null
  created_at: string
}

export interface ApiKeyCreated extends ApiKey {
  api_key: string
}

export interface AuditEntry {
  id: string
  actor_id: string | null
  action: string
  resource_type: string
  resource_id: string | null
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  ip_address: string | null
  user_agent: string | null
  created_at: string
}

export interface MetricsSummary {
  mtta_seconds: number | null
  mttr_seconds: number | null
  weekly_by_severity: { week: string; severity: Severity; count: number; cumulative: number }[]
  top_services: { service_id: string; name: string; count: number; rank: number }[]
}
