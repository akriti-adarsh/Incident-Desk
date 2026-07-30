// Shared UI primitives. Kept deliberately small and semantic; styling lives in
// ui.css using the design tokens.

import { type ButtonHTMLAttributes, type ReactNode, forwardRef } from 'react'

import type { IncidentStatus, Severity } from '../api/types'
import { SEVERITY_LABEL, STATUS_LABEL } from '../lib/format'
import './ui.css'

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  loading?: boolean
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', loading, children, disabled, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      className={`btn btn-${variant}`}
      disabled={disabled ?? loading}
      aria-busy={loading}
      {...rest}
    >
      {loading ? <span className="btn-spinner" aria-hidden /> : null}
      {children}
    </button>
  )
})

export function SeverityBadge({ severity }: { severity: Severity }) {
  // Severity is never colour alone: glyph + label + border weight carry it too.
  const filled = severity === 'sev1' || severity === 'sev2'
  return (
    <span className={`sev sev-${severity}`} data-severity={severity}>
      <span className="sev-glyph" aria-hidden>
        {filled ? '■' : '□'}
      </span>
      {SEVERITY_LABEL[severity]}
    </span>
  )
}

export function StatusBadge({ status }: { status: IncidentStatus }) {
  return (
    <span className={`status status-${status}`}>
      <span className="status-dot" aria-hidden />
      {STATUS_LABEL[status]}
    </span>
  )
}

export function Field({
  label,
  htmlFor,
  error,
  children,
  hint,
}: {
  label: string
  htmlFor: string
  error?: string
  hint?: string
  children: ReactNode
}) {
  return (
    <div className="field">
      <label htmlFor={htmlFor}>{label}</label>
      {children}
      {hint && !error ? <p className="field-hint">{hint}</p> : null}
      {error ? (
        <p className="field-error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  )
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={`card ${className ?? ''}`}>{children}</div>
}

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return (
    <span className="spinner" role="status" aria-label={label}>
      <span className="spinner-ring" aria-hidden />
    </span>
  )
}

export function Skeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="skeleton" aria-hidden>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skeleton-row" />
      ))}
    </div>
  )
}

export function EmptyState({
  title,
  children,
}: {
  title: string
  children?: ReactNode
}) {
  return (
    <div className="empty">
      <p className="empty-title">{title}</p>
      {children ? <div className="empty-body">{children}</div> : null}
    </div>
  )
}
