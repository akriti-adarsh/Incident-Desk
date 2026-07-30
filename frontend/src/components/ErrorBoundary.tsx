import { Component, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}
interface State {
  error: Error | null
}

// Per-route error boundary. Shows the request id when the failure carried one
// (our ApiError does), so a user can quote it in a support request.
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  render() {
    if (this.state.error) {
      const requestId = (this.state.error as { requestId?: string }).requestId
      return (
        <div className="route-error" role="alert">
          <h1>Something broke</h1>
          <p>This screen hit an error it could not recover from. Reload to try again.</p>
          {requestId ? <p className="mono">Reference: {requestId}</p> : null}
          <button className="btn btn-secondary" onClick={() => this.setState({ error: null })}>
            Try again
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
