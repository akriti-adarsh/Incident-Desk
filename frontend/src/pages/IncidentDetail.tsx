// Incident detail: the timeline is the spine, metadata rails around it. Status
// transitions offer only legal moves; comments post optimistically and roll
// back on failure; attachments upload with drag-and-drop; presence is live.

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { useParams } from 'react-router-dom'

import { ApiError, request } from '../api/client'
import type { Comment, Data, IncidentStatus } from '../api/types'
import {
  keys,
  uploadAttachment,
  useAttachmentsQuery,
  useChangeStatus,
  useComments,
  useIncident,
  useMembers,
  useTimeline,
} from '../api/queries'
import { Timeline } from '../components/Timeline'
import { Modal } from '../components/Modal'
import { Button, Field, SeverityBadge, Skeleton, StatusBadge } from '../components/ui'
import { LEGAL_TRANSITIONS, STATUS_LABEL, formatBytes, relativeTime } from '../lib/format'
import { can } from '../lib/permissions'
import { usePresence } from '../lib/useRealtime'
import { useOrgContext } from '../lib/useOrgContext'
import { toast } from '../store/ui'
import { useAuth } from '../store/auth'
import './incident-detail.css'

export function IncidentDetailPage() {
  const { incidentId = '' } = useParams()
  const { slug, role } = useOrgContext()
  const qc = useQueryClient()
  const me = useAuth((s) => s.user)

  const incident = useIncident(slug, incidentId)
  const timeline = useTimeline(slug, incidentId)
  const comments = useComments(slug, incidentId)
  const attachments = useAttachmentsQuery(slug, incidentId)
  const members = useMembers(slug)
  const changeStatus = useChangeStatus(slug, incidentId)
  const viewers = usePresence(slug, incidentId)

  const [resolveOpen, setResolveOpen] = useState(false)
  const [commentBody, setCommentBody] = useState('')
  const [dragging, setDragging] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const memberName = (id: string | null) =>
    members.data?.data.find((m) => m.user_id === id)?.full_name ?? 'Unknown'

  const addComment = useMutation({
    mutationFn: (body: string) =>
      request<Data<Comment>>(`/api/v1/orgs/${slug}/incidents/${incidentId}/comments`, {
        method: 'POST',
        body: { body },
      }),
    onMutate: async (body) => {
      await qc.cancelQueries({ queryKey: keys.comments(slug, incidentId) })
      const previous = qc.getQueryData(keys.comments(slug, incidentId))
      const optimistic: Comment = {
        id: `optimistic-${Date.now()}`,
        author_id: me?.id ?? '',
        body,
        edited_at: null,
        created_at: new Date().toISOString(),
      }
      qc.setQueryData<{ data: Comment[]; next_cursor: string | null }>(
        keys.comments(slug, incidentId),
        (old) => ({
          data: [...(old?.data ?? []), optimistic],
          next_cursor: old?.next_cursor ?? null,
        }),
      )
      return { previous }
    },
    onError: (_err, _body, ctx) => {
      // Roll back the optimistic comment.
      if (ctx?.previous) qc.setQueryData(keys.comments(slug, incidentId), ctx.previous)
      toast('error', 'Your comment did not post. Try again.')
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: keys.comments(slug, incidentId) })
      qc.invalidateQueries({ queryKey: keys.events(slug, incidentId) })
    },
  })

  async function doStatus(status: IncidentStatus, resolution?: string) {
    try {
      await changeStatus.mutateAsync({ status, resolution_summary: resolution })
      toast('success', `Incident ${STATUS_LABEL[status].toLowerCase()}`)
      setResolveOpen(false)
    } catch (err) {
      toast('error', err instanceof ApiError ? err.message : 'Could not change the status.')
    }
  }

  async function handleFiles(files: FileList | null) {
    if (!files?.length) return
    try {
      for (const file of Array.from(files)) {
        await uploadAttachment(slug, incidentId, file)
      }
      toast('success', 'Attachment uploaded')
      attachments.refetch()
      timeline.refetch()
    } catch {
      toast('error', 'Upload failed. Check the file size and try again.')
    }
  }

  if (incident.isPending) return <Skeleton rows={10} />
  if (incident.isError || !incident.data) {
    return <p className="route-error">This incident could not be loaded.</p>
  }
  const inc = incident.data.data
  const nextStatuses = LEGAL_TRANSITIONS[inc.status]
  const canUpdate = can(role, 'incident:update')

  return (
    <div className="detail">
      <header className="detail-head">
        <div className="detail-title">
          <span className="mono detail-number">{inc.number}</span>
          <h1>{inc.title}</h1>
        </div>
        <div className="detail-meta">
          <SeverityBadge severity={inc.severity} />
          <StatusBadge status={inc.status} />
          {viewers.length > 0 ? (
            <span className="presence" title="People viewing now">
              <span className="presence-dot" aria-hidden /> {viewers.length} viewing
            </span>
          ) : null}
        </div>
      </header>

      <div className="detail-grid">
        <section className="detail-spine" aria-label="Timeline">
          {inc.description ? <p className="detail-desc">{inc.description}</p> : null}
          {timeline.isPending ? <Skeleton rows={4} /> : <Timeline events={timeline.data?.data ?? []} />}

          <section className="comments" aria-label="Comments">
            {(comments.data?.data ?? []).map((c) => (
              <div key={c.id} className={`comment ${c.id.startsWith('optimistic') ? 'comment-pending' : ''}`}>
                <div className="comment-head">
                  <span className="comment-author">{memberName(c.author_id)}</span>
                  <time className="comment-time">{relativeTime(c.created_at)}</time>
                </div>
                <p className="comment-body">{c.body}</p>
              </div>
            ))}
          </section>

          {can(role, 'comment:create') ? (
            <form
              className="composer"
              onSubmit={(e) => {
                e.preventDefault()
                if (!commentBody.trim()) return
                addComment.mutate(commentBody.trim())
                setCommentBody('')
              }}
            >
              <textarea
                value={commentBody}
                onChange={(e) => setCommentBody(e.target.value)}
                placeholder="Add a comment. Markdown is supported."
                aria-label="Add a comment"
              />
              <Button type="submit" variant="primary" disabled={!commentBody.trim()}>
                Comment
              </Button>
            </form>
          ) : null}
        </section>

        <aside className="detail-rail">
          <div className="rail-block">
            <h2>Status</h2>
            {canUpdate && nextStatuses.length > 0 ? (
              <div className="status-actions">
                {nextStatuses.map((s) =>
                  s === 'resolved' ? (
                    <Button key={s} variant="danger" onClick={() => setResolveOpen(true)}>
                      Resolve incident
                    </Button>
                  ) : (
                    <Button key={s} onClick={() => doStatus(s)}>
                      {STATUS_LABEL[s]}
                    </Button>
                  ),
                )}
              </div>
            ) : (
              <p className="rail-muted">
                {inc.status === 'postmortem' ? 'This incident is closed.' : 'No actions available.'}
              </p>
            )}
          </div>

          <div className="rail-block">
            <h2>Assignee</h2>
            <p className="rail-value">{inc.assigned_to ? memberName(inc.assigned_to) : 'Unassigned'}</p>
          </div>

          <div className="rail-block">
            <h2>Reported by</h2>
            <p className="rail-value">{memberName(inc.reported_by)}</p>
          </div>

          {inc.tags.length ? (
            <div className="rail-block">
              <h2>Tags</h2>
              <div className="tag-list">
                {inc.tags.map((t) => (
                  <span key={t} className="chip">
                    {t}
                  </span>
                ))}
              </div>
            </div>
          ) : null}

          <div className="rail-block">
            <h2>Attachments</h2>
            {can(role, 'attachment:upload') ? (
              <div
                className={`dropzone ${dragging ? 'dropzone-active' : ''}`}
                onDragOver={(e) => {
                  e.preventDefault()
                  setDragging(true)
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={(e) => {
                  e.preventDefault()
                  setDragging(false)
                  handleFiles(e.dataTransfer.files)
                }}
                onClick={() => fileRef.current?.click()}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => e.key === 'Enter' && fileRef.current?.click()}
              >
                Drop a file here, or click to choose
                <input
                  ref={fileRef}
                  type="file"
                  hidden
                  onChange={(e) => handleFiles(e.target.files)}
                />
              </div>
            ) : null}
            <ul className="attachment-list">
              {(attachments.data?.data ?? []).map((a) => (
                <li key={a.id}>
                  <span className="attachment-name">{a.filename}</span>
                  <span className="attachment-size">{formatBytes(a.size_bytes)}</span>
                </li>
              ))}
            </ul>
          </div>
        </aside>
      </div>

      {resolveOpen ? (
        <ResolveDialog
          onClose={() => setResolveOpen(false)}
          onResolve={(summary) => doStatus('resolved', summary)}
        />
      ) : null}
    </div>
  )
}

function ResolveDialog({
  onClose,
  onResolve,
}: {
  onClose: () => void
  onResolve: (summary: string) => void
}) {
  const [summary, setSummary] = useState('')
  return (
    <Modal title="Resolve incident" onClose={onClose} danger>
      <p className="rail-muted">A resolution summary is required. Say what happened and how it was fixed.</p>
      <Field label="Resolution summary" htmlFor="resolution">
        <textarea id="resolution" value={summary} onChange={(e) => setSummary(e.target.value)} autoFocus />
      </Field>
      <div className="modal-actions">
        <Button type="button" onClick={onClose}>
          Cancel
        </Button>
        <Button variant="danger" disabled={!summary.trim()} onClick={() => onResolve(summary.trim())}>
          Resolve incident
        </Button>
      </div>
    </Modal>
  )
}
