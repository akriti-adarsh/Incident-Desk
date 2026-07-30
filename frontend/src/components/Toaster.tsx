import { useToasts } from '../store/ui'
import './toaster.css'

export function Toaster() {
  const { toasts, dismiss } = useToasts()
  return (
    <div className="toaster" role="region" aria-label="Notifications" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast-${t.kind}`}>
          <div className="toast-body">
            <p className="toast-message">{t.message}</p>
            {t.requestId ? <p className="toast-request">ref {t.requestId}</p> : null}
          </div>
          <button className="toast-close" onClick={() => dismiss(t.id)} aria-label="Dismiss">
            &times;
          </button>
        </div>
      ))}
    </div>
  )
}
