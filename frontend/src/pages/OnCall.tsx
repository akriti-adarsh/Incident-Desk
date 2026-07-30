// On-call: who is on call now (per service), and a week view of shifts.

import { useState } from 'react'

import { useSchedules, useServices, useShifts, useWhoIsOnCall } from '../api/queries'
import { EmptyState, Skeleton } from '../components/ui'
import { useOrgContext } from '../lib/useOrgContext'
import './oncall.css'

function startOfWeek(d: Date): Date {
  const copy = new Date(d)
  const day = (copy.getDay() + 6) % 7
  copy.setDate(copy.getDate() - day)
  copy.setHours(0, 0, 0, 0)
  return copy
}

export function OnCallPage() {
  const { slug } = useOrgContext()
  const services = useServices(slug)
  const schedules = useSchedules(slug)
  const [serviceId, setServiceId] = useState<string | undefined>(undefined)
  const activeService = serviceId ?? services.data?.data[0]?.id
  const whoIsOnCall = useWhoIsOnCall(slug, activeService)

  const weekStart = startOfWeek(new Date())
  const days = Array.from({ length: 7 }, (_, i) => {
    const d = new Date(weekStart)
    d.setDate(d.getDate() + i)
    return d
  })

  return (
    <div className="oncall">
      <header className="page-head">
        <h1>On-call</h1>
        <select
          value={activeService ?? ''}
          onChange={(e) => setServiceId(e.target.value)}
          aria-label="Choose a service"
          style={{ width: 'auto' }}
        >
          {(services.data?.data ?? []).map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </header>

      <section className="oncall-now card" aria-label="Who is on call now">
        <h2>On call right now</h2>
        {whoIsOnCall.isPending ? (
          <Skeleton rows={2} />
        ) : (whoIsOnCall.data?.data.length ?? 0) === 0 ? (
          <p className="rail-muted">No schedule for this service yet.</p>
        ) : (
          <ul className="oncall-strip">
            {(whoIsOnCall.data?.data ?? []).map((entry) => (
              <li key={entry.schedule_id}>
                <span className="oncall-schedule">{entry.schedule_name}</span>
                <span className={`oncall-person ${entry.on_call ? '' : 'oncall-nobody'}`}>
                  {entry.on_call ? entry.on_call.full_name : 'Nobody on call'}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-label="This week">
        <h2 className="week-title">This week</h2>
        {schedules.isPending ? (
          <Skeleton rows={4} />
        ) : (schedules.data?.data.length ?? 0) === 0 ? (
          <EmptyState title="No schedules">
            An admin can create an on-call schedule for a service to fill this in.
          </EmptyState>
        ) : (
          (schedules.data?.data ?? [])
            .filter((sch) => sch.service_id === activeService)
            .map((sch) => <WeekRow key={sch.id} org={slug} scheduleId={sch.id} name={sch.name} days={days} />)
        )}
      </section>
    </div>
  )
}

function WeekRow({
  org,
  scheduleId,
  name,
  days,
}: {
  org: string
  scheduleId: string
  name: string
  days: Date[]
}) {
  const from = days[0]?.toISOString()
  const last = days[days.length - 1]
  const to = last ? new Date(last.getTime() + 86400000).toISOString() : undefined
  const shifts = useShifts(org, scheduleId, from, to)

  return (
    <div className="week-row card">
      <div className="week-name">{name}</div>
      <div className="week-grid">
        {days.map((day) => {
          const covering = (shifts.data?.data ?? []).filter(
            (s) => new Date(s.starts_at) < new Date(day.getTime() + 86400000) && new Date(s.ends_at) > day,
          )
          return (
            <div key={day.toISOString()} className="week-cell">
              <span className="week-day">{day.toLocaleDateString(undefined, { weekday: 'short' })}</span>
              {covering.length > 0 ? <span className="week-shift" aria-label="Covered" /> : null}
            </div>
          )
        })}
      </div>
    </div>
  )
}
