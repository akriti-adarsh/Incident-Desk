// The app shell: sidebar nav (role-gated), org switcher, theme toggle, and the
// routed outlet. The active org scopes every nested route.

import { NavLink, Outlet, useNavigate } from 'react-router-dom'

import type { Permission } from '../lib/permissions'
import { can } from '../lib/permissions'
import { activeOrg, useAuth } from '../store/auth'
import { useTheme } from '../store/ui'
import { Toaster } from './Toaster'
import './layout.css'

interface NavItem {
  to: string
  label: string
  permission: Permission
}

const NAV: NavItem[] = [
  { to: 'incidents', label: 'Incidents', permission: 'incident:view' },
  { to: 'on-call', label: 'On-call', permission: 'oncall:view' },
  { to: 'metrics', label: 'Metrics', permission: 'metrics:view' },
  { to: 'settings', label: 'Settings', permission: 'member:view' },
]

export function Layout() {
  const navigate = useNavigate()
  const { user, orgs, activeOrgSlug, setActiveOrg, logout } = useAuth()
  const org = activeOrg(useAuth.getState())
  const role = org?.role ?? null
  const { theme, toggle } = useTheme()

  return (
    <div className="shell">
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden>
            ▚
          </span>
          <span className="brand-name">incident-desk</span>
        </div>

        <div className="org-switcher">
          <label htmlFor="org-select" className="org-label">
            Organisation
          </label>
          <select
            id="org-select"
            value={activeOrgSlug ?? ''}
            onChange={(e) => {
              setActiveOrg(e.target.value)
              navigate(`/o/${e.target.value}/incidents`)
            }}
          >
            {orgs.map((o) => (
              <option key={o.id} value={o.slug}>
                {o.name}
              </option>
            ))}
          </select>
          {role ? <span className="org-role">{role}</span> : null}
        </div>

        <nav className="nav" aria-label="Primary">
          {NAV.filter((item) => can(role, item.permission)).map((item) => (
            <NavLink
              key={item.to}
              to={`/o/${activeOrgSlug}/${item.to}`}
              className={({ isActive }) => `nav-item ${isActive ? 'nav-active' : ''}`}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-foot">
          <button className="theme-toggle" onClick={toggle} aria-label="Toggle theme">
            {theme === 'dark' ? '☾' : '☀'} {theme === 'dark' ? 'Dark' : 'Light'}
          </button>
          <div className="account">
            <span className="account-name">{user?.full_name}</span>
            <button className="link-btn" onClick={() => void logout().then(() => navigate('/login'))}>
              Sign out
            </button>
          </div>
        </div>
      </aside>

      <main id="main" className="content" tabIndex={-1}>
        <Outlet />
      </main>
      <Toaster />
    </div>
  )
}
