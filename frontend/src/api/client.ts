// The typed API client: one fetch wrapper that carries the access token,
// transparently refreshes it once on a 401, surfaces the server's error
// envelope (code + request_id) as a typed ApiError, and returns parsed JSON.

import type { ApiErrorBody } from './types'

export const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly requestId: string
  readonly details: unknown

  constructor(status: number, body: ApiErrorBody) {
    super(body.error.message)
    this.name = 'ApiError'
    this.status = status
    this.code = body.error.code
    this.requestId = body.error.request_id
    this.details = body.error.details
  }
}

// The client holds the access token in memory only (never localStorage, so an
// XSS payload cannot read it). The rotating refresh token lives in localStorage
// so a page reload can re-establish a session; theft of it is detected and
// punished server-side by the refresh-token-family machinery.
let accessToken: string | null = null
let onUnauthorized: (() => void) | null = null

export function setAccessToken(token: string | null): void {
  accessToken = token
}

export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler
}

const REFRESH_KEY = 'incident_desk.refresh'

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY)
}

export function setRefreshToken(token: string | null): void {
  if (token) localStorage.setItem(REFRESH_KEY, token)
  else localStorage.removeItem(REFRESH_KEY)
}

interface RequestOptions {
  method?: string
  body?: unknown
  headers?: Record<string, string>
  query?: Record<string, string | number | string[] | undefined>
  signal?: AbortSignal
  raw?: boolean
}

function buildUrl(path: string, query?: RequestOptions['query']): string {
  const url = new URL(API_BASE + path)
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined) continue
      if (Array.isArray(value)) value.forEach((v) => url.searchParams.append(key, v))
      else url.searchParams.set(key, String(value))
    }
  }
  return url.toString()
}

let refreshInFlight: Promise<boolean> | null = null

async function refreshAccessToken(): Promise<boolean> {
  const refresh = getRefreshToken()
  if (!refresh) return false
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const response = await fetch(buildUrl('/api/v1/auth/refresh'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: refresh }),
        })
        if (!response.ok) return false
        const { data } = (await response.json()) as {
          data: { access_token: string; refresh_token: string }
        }
        accessToken = data.access_token
        setRefreshToken(data.refresh_token)
        return true
      } catch {
        return false
      } finally {
        refreshInFlight = null
      }
    })()
  }
  return refreshInFlight
}

async function raw(path: string, options: RequestOptions, retry = true): Promise<Response> {
  const headers: Record<string, string> = { ...options.headers }
  if (options.body !== undefined && !(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'
  }
  if (accessToken) headers['Authorization'] = `Bearer ${accessToken}`

  const response = await fetch(buildUrl(path, options.query), {
    method: options.method ?? 'GET',
    headers,
    body:
      options.body instanceof FormData
        ? options.body
        : options.body !== undefined
          ? JSON.stringify(options.body)
          : undefined,
    signal: options.signal,
  })

  if (response.status === 401 && retry && (await refreshAccessToken())) {
    return raw(path, options, false)
  }
  if (response.status === 401 && onUnauthorized) onUnauthorized()
  return response
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await raw(path, options)
  if (options.raw) return response as unknown as T
  if (response.status === 204) return undefined as T
  const text = await response.text()
  const json = text ? JSON.parse(text) : {}
  if (!response.ok) throw new ApiError(response.status, json as ApiErrorBody)
  return json as T
}

export function requestResponse(path: string, options: RequestOptions = {}): Promise<Response> {
  return raw(path, { ...options })
}
