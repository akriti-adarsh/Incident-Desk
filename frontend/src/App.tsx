import { useEffect } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import { OrgRoutes } from './app/OrgRoutes'
import { ErrorBoundary } from './components/ErrorBoundary'
import { Spinner } from './components/ui'
import {
  ForgotPasswordPage,
  LoginPage,
  RegisterPage,
  ResetPasswordPage,
  VerifyEmailPage,
} from './pages/auth'
import { IncidentDetailPage } from './pages/IncidentDetail'
import { IncidentsPage } from './pages/Incidents'
import { MetricsPage } from './pages/Metrics'
import { ForbiddenPage, NotFoundPage, OnboardingPage } from './pages/misc'
import { OnCallPage } from './pages/OnCall'
import { SettingsPage } from './pages/Settings'
import { setUnauthorizedHandler } from './api/client'
import { useAuth } from './store/auth'
import { useTheme } from './store/ui'

function Protected({ children }: { children: React.ReactNode }) {
  const status = useAuth((s) => s.status)
  if (status === 'loading') {
    return (
      <div className="app-loading">
        <Spinner label="Loading your session" />
      </div>
    )
  }
  if (status === 'anonymous') return <Navigate to="/login" replace />
  return <ErrorBoundary>{children}</ErrorBoundary>
}

function Anonymous({ children }: { children: React.ReactNode }) {
  const status = useAuth((s) => s.status)
  if (status === 'authenticated') {
    const { activeOrgSlug } = useAuth.getState()
    return <Navigate to={activeOrgSlug ? `/o/${activeOrgSlug}/incidents` : '/onboarding'} replace />
  }
  return <>{children}</>
}

export default function App() {
  const bootstrap = useAuth((s) => s.bootstrap)
  const logout = useAuth((s) => s.logout)
  const theme = useTheme((s) => s.theme)

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
  }, [theme])

  useEffect(() => {
    setUnauthorizedHandler(() => {
      void logout()
    })
    void bootstrap()
  }, [bootstrap, logout])

  return (
    <Routes>
      <Route path="/login" element={<Anonymous><LoginPage /></Anonymous>} />
      <Route path="/register" element={<Anonymous><RegisterPage /></Anonymous>} />
      <Route path="/verify-email" element={<VerifyEmailPage />} />
      <Route path="/forgot-password" element={<Anonymous><ForgotPasswordPage /></Anonymous>} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route path="/onboarding" element={<Protected><OnboardingPage /></Protected>} />

      <Route path="/o/:orgSlug" element={<Protected><OrgRoutes /></Protected>}>
        <Route index element={<Navigate to="incidents" replace />} />
        <Route path="incidents" element={<IncidentsPage />} />
        <Route path="incidents/:incidentId" element={<IncidentDetailPage />} />
        <Route path="on-call" element={<OnCallPage />} />
        <Route path="metrics" element={<MetricsPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="forbidden" element={<ForbiddenPage />} />
      </Route>

      <Route path="/" element={<Navigate to="/login" replace />} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  )
}
