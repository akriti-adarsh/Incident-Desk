// The signature element: the incident timeline as a vertical spine. Every
// event is a node on a continuous line; system events (no actor) are visually
// distinct from human actions.

import type { TimelineEvent } from '../api/types'
import { relativeTime } from '../lib/format'
import './timeline.css'

const GLYPH: Record<string, string> = {
  'incident.created': '✳',
  'status.changed': '◆',
  'severity.changed': '▲',
  'assignment.changed': '⇄',
  'incident.updated': '✎',
  'comment.added': '❝',
  'comment.edited': '✎',
  'comment.deleted': '✕',
  'attachment.added': '📎',
  'attachment.scan_skipped': '🛈',
  'escalation.notified': '⚑',
}

function describe(event: TimelineEvent): string {
  const p = event.payload as Record<string, string>
  switch (event.event_type) {
    case 'incident.created':
      return `Reported as ${p.number ?? 'an incident'} (${p.severity ?? ''})`
    case 'status.changed':
      return `Status: ${p.from} to ${p.to}`
    case 'severity.changed':
      return `Severity: ${p.from} to ${p.to}`
    case 'assignment.changed':
      return p.to ? 'Assignment changed' : 'Unassigned'
    case 'comment.added':
      return 'Comment added'
    case 'comment.edited':
      return 'Comment edited'
    case 'comment.deleted':
      return 'Comment removed'
    case 'attachment.added':
      return `Attachment: ${p.filename ?? 'file'}`
    case 'attachment.scan_skipped':
      return 'Attachment scan skipped (no scanner configured)'
    case 'escalation.notified':
      return `Escalated to level ${p.level}`
    case 'incident.updated':
      return 'Details edited'
    default:
      return event.event_type
  }
}

export function Timeline({ events }: { events: TimelineEvent[] }) {
  return (
    <ol className="timeline" aria-label="Incident timeline">
      {events.map((event) => {
        const system = event.actor_id === null
        return (
          <li key={event.id} className={`tl-node ${system ? 'tl-system' : ''}`}>
            <span className="tl-glyph" aria-hidden>
              {GLYPH[event.event_type] ?? '•'}
            </span>
            <div className="tl-content">
              <p className="tl-desc">
                {describe(event)}
                {system ? <span className="tl-tag">system</span> : null}
              </p>
              <time className="tl-time" dateTime={event.created_at}>
                {relativeTime(event.created_at)}
              </time>
            </div>
          </li>
        )
      })}
    </ol>
  )
}
