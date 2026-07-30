import { useEffect, useRef, type ReactNode } from 'react'

import './modal.css'

// Accessible dialog: focus is trapped, Escape closes, the backdrop closes, and
// focus returns to the opener on close.
export function Modal({
  title,
  onClose,
  children,
  danger,
}: {
  title: string
  onClose: () => void
  children: ReactNode
  danger?: boolean
}) {
  const ref = useRef<HTMLDivElement>(null)
  const opener = useRef<Element | null>(null)

  useEffect(() => {
    opener.current = document.activeElement
    const el = ref.current
    el?.querySelector<HTMLElement>('input, textarea, select, button')?.focus()

    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
      if (e.key === 'Tab' && el) {
        const focusable = el.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input, textarea, select, [tabindex]:not([tabindex="-1"])',
        )
        const first = focusable[0]
        const last = focusable[focusable.length - 1]
        if (!first || !last) return
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault()
          last.focus()
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault()
          first.focus()
        }
      }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      ;(opener.current as HTMLElement | null)?.focus?.()
    }
  }, [onClose])

  return (
    <div className="modal-backdrop">
      {/* A real button behind the dialog provides click-to-close accessibly. */}
      <button className="modal-backdrop-btn" aria-label="Close dialog" onClick={onClose} tabIndex={-1} />
      <div
        ref={ref}
        className={`modal ${danger ? 'modal-danger' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="modal-close" onClick={onClose} aria-label="Close">
            &times;
          </button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  )
}
