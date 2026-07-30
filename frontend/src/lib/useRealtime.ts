// WebSocket subscriptions with precise query invalidation.
//
// Connection: POST /ws-ticket for a single-use ticket, connect with ?ticket=,
// heartbeat with a ping every 20s. On drop, reconnect with exponential backoff
// and, crucially, refetch to reconcile anything missed while disconnected: the
// socket is a change notifier, not reliable delivery.
//
// Events invalidate exactly the affected query keys, never a blanket refetch.

import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'

import { API_BASE, request } from '../api/client'
import { invalidateIncidentKeys, keys } from '../api/queries'

const HEARTBEAT_MS = 20_000
const MAX_BACKOFF_MS = 15_000

interface ServerEvent {
  type: string
  incident_id?: string
  viewers?: string[]
  [key: string]: unknown
}

function wsUrl(ticket: string): string {
  const base = API_BASE.replace(/^http/, 'ws')
  return `${base}/ws?ticket=${encodeURIComponent(ticket)}`
}

// Subscribe to an org's incident stream; list/detail views stay fresh across
// replicas without polling.
export function useOrgIncidentStream(org: string): void {
  const qc = useQueryClient()
  useEffect(() => {
    if (!org) return
    const channel = `org:${org}:incidents`
    const stop = connect(channel, (event) => {
      invalidateIncidentKeys(qc, org, event.incident_id)
    }, () => {
      // Reconcile on reconnect.
      qc.invalidateQueries({ queryKey: ['incidents', org] })
    })
    return stop
  }, [org, qc])
}

// Subscribe to a single incident (comments, status, presence) and expose the
// live viewer list.
export function usePresence(org: string, incidentId: string): string[] {
  const qc = useQueryClient()
  const [viewers, setViewers] = useState<string[]>([])
  useEffect(() => {
    if (!org || !incidentId) return
    const channel = `incident:${incidentId}`
    const stop = connect(
      channel,
      (event) => {
        if (event.type === 'presence.changed' && Array.isArray(event.viewers)) {
          setViewers(event.viewers)
        } else if (event.type === 'comment.added') {
          qc.invalidateQueries({ queryKey: keys.comments(org, incidentId) })
          qc.invalidateQueries({ queryKey: keys.events(org, incidentId) })
        } else if (event.type === 'incident.status_changed' || event.type === 'incident.updated') {
          qc.invalidateQueries({ queryKey: keys.incident(org, incidentId) })
          qc.invalidateQueries({ queryKey: keys.events(org, incidentId) })
        }
      },
      () => {
        qc.invalidateQueries({ queryKey: keys.incident(org, incidentId) })
        qc.invalidateQueries({ queryKey: keys.comments(org, incidentId) })
        qc.invalidateQueries({ queryKey: keys.events(org, incidentId) })
      },
    )
    return stop
  }, [org, incidentId, qc])
  return viewers
}

// One reconnecting subscription to a channel. Returns a teardown function.
function connect(
  channel: string,
  onEvent: (event: ServerEvent) => void,
  onReconnect: () => void,
): () => void {
  let ws: WebSocket | null = null
  let heartbeat: ReturnType<typeof setInterval> | null = null
  let backoff = 500
  let closed = false
  let hadConnection = false

  async function open() {
    if (closed) return
    try {
      const res = await request<{ data: { ticket: string } }>('/api/v1/ws-ticket', {
        method: 'POST',
      })
      ws = new WebSocket(wsUrl(res.data.ticket))
    } catch {
      schedule()
      return
    }

    ws.onopen = () => {
      backoff = 500
      ws?.send(JSON.stringify({ action: 'subscribe', channel }))
      if (hadConnection) onReconnect()
      hadConnection = true
      heartbeat = setInterval(() => ws?.send(JSON.stringify({ action: 'ping' })), HEARTBEAT_MS)
    }
    ws.onmessage = (msg) => {
      try {
        onEvent(JSON.parse(msg.data) as ServerEvent)
      } catch {
        /* ignore malformed frames */
      }
    }
    ws.onclose = () => {
      if (heartbeat) clearInterval(heartbeat)
      schedule()
    }
    ws.onerror = () => ws?.close()
  }

  function schedule() {
    if (closed) return
    backoff = Math.min(backoff * 2, MAX_BACKOFF_MS)
    setTimeout(open, backoff)
  }

  void open()

  return () => {
    closed = true
    if (heartbeat) clearInterval(heartbeat)
    ws?.close()
  }
}

export function useRealtimeRef(): React.MutableRefObject<WebSocket | null> {
  return useRef<WebSocket | null>(null)
}
