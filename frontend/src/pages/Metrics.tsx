// Metrics dashboard: MTTA/MTTR, incidents by severity over time, top services.

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import type { Severity } from '../api/types'
import { useMetrics } from '../api/queries'
import { EmptyState, Skeleton } from '../components/ui'
import { formatDuration } from '../lib/format'
import { useOrgContext } from '../lib/useOrgContext'
import './metrics.css'

const SEV_COLOR: Record<Severity, string> = {
  sev1: '#f0476b',
  sev2: '#f2a63b',
  sev3: '#3d8bff',
  sev4: '#7d8798',
}

export function MetricsPage() {
  const { slug } = useOrgContext()
  const metrics = useMetrics(slug)

  if (metrics.isPending) return <Skeleton rows={10} />
  const data = metrics.data?.data
  if (!data) return <EmptyState title="No metrics yet">Metrics appear once incidents exist.</EmptyState>

  // Pivot weekly-by-severity into rows keyed by week for the stacked view.
  const byWeek = new Map<string, Record<string, number | string>>()
  for (const row of data.weekly_by_severity) {
    const entry = byWeek.get(row.week) ?? { week: row.week }
    entry[row.severity] = row.count
    byWeek.set(row.week, entry)
  }
  const weekly = [...byWeek.values()].sort((a, b) => String(a.week).localeCompare(String(b.week)))

  const trend = data.weekly_by_severity
    .filter((r) => r.severity === 'sev1' || r.severity === 'sev2')
    .reduce<Record<string, { week: string; cumulative: number }>>((acc, r) => {
      acc[r.week] = { week: r.week, cumulative: (acc[r.week]?.cumulative ?? 0) + r.cumulative }
      return acc
    }, {})
  const trendData = Object.values(trend).sort((a, b) => a.week.localeCompare(b.week))

  return (
    <div className="metrics">
      <h1>Metrics</h1>

      <div className="stat-row">
        <div className="stat card">
          <span className="stat-label">Mean time to acknowledge</span>
          <span className="stat-value">{formatDuration(data.mtta_seconds)}</span>
        </div>
        <div className="stat card">
          <span className="stat-label">Mean time to resolve</span>
          <span className="stat-value">{formatDuration(data.mttr_seconds)}</span>
        </div>
        <div className="stat card">
          <span className="stat-label">Top service</span>
          <span className="stat-value stat-value-sm">
            {data.top_services[0]?.name ?? 'n/a'}
          </span>
        </div>
      </div>

      <div className="chart-grid">
        <div className="chart card">
          <h2>Incidents by severity</h2>
          {weekly.length === 0 ? (
            <p className="rail-muted">No incidents in the window.</p>
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={weekly}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="week" tick={{ fontSize: 11, fill: 'var(--ink-faint)' }} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: 'var(--ink-faint)' }} />
                <Tooltip contentStyle={{ background: 'var(--surface-3)', border: '1px solid var(--border-strong)' }} />
                <Legend />
                {(['sev1', 'sev2', 'sev3', 'sev4'] as Severity[]).map((sev) => (
                  <Bar key={sev} dataKey={sev} stackId="s" fill={SEV_COLOR[sev]} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="chart card">
          <h2>Cumulative high-severity trend</h2>
          {trendData.length === 0 ? (
            <p className="rail-muted">No high-severity incidents yet.</p>
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={trendData}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="week" tick={{ fontSize: 11, fill: 'var(--ink-faint)' }} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: 'var(--ink-faint)' }} />
                <Tooltip contentStyle={{ background: 'var(--surface-3)', border: '1px solid var(--border-strong)' }} />
                <Line type="monotone" dataKey="cumulative" stroke="var(--amber)" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      <div className="chart card">
        <h2>Top affected services</h2>
        {data.top_services.length === 0 ? (
          <p className="rail-muted">No incidents recorded yet.</p>
        ) : (
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={data.top_services} layout="vertical">
              <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11, fill: 'var(--ink-faint)' }} />
              <YAxis type="category" dataKey="name" width={140} tick={{ fontSize: 11, fill: 'var(--ink-muted)' }} />
              <Tooltip contentStyle={{ background: 'var(--surface-3)', border: '1px solid var(--border-strong)' }} />
              <Bar dataKey="count" fill="var(--pulse)">
                {data.top_services.map((s) => (
                  <Cell key={s.service_id} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}
