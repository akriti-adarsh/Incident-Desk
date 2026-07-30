// Client auth state: the current user, the active org, and session lifecycle.
// Tokens themselves live in the api client; this store holds the derived
// identity the UI renders and the active-org selection that scopes every view.

import { create } from 'zustand'

import {
  getRefreshToken,
  request,
  setAccessToken,
  setRefreshToken,
} from '../api/client'
import type { OrgWithRole, TokenPair, User } from '../api/types'

const ACTIVE_ORG_KEY = 'incident_desk.active_org'

interface AuthState {
  user: User | null
  orgs: OrgWithRole[]
  activeOrgSlug: string | null
  status: 'loading' | 'authenticated' | 'anonymous'

  bootstrap: () => Promise<void>
  applyTokens: (tokens: TokenPair) => Promise<void>
  loadSession: () => Promise<void>
  setActiveOrg: (slug: string) => void
  logout: () => Promise<void>
}

function readActiveOrg(): string | null {
  return localStorage.getItem(ACTIVE_ORG_KEY)
}

export const useAuth = create<AuthState>((set, get) => ({
  user: null,
  orgs: [],
  activeOrgSlug: readActiveOrg(),
  status: 'loading',

  bootstrap: async () => {
    // A refresh token in storage means we can silently resume a session on
    // reload; without one the user is anonymous.
    if (!getRefreshToken()) {
      set({ status: 'anonymous' })
      return
    }
    try {
      await get().loadSession()
    } catch {
      setRefreshToken(null)
      setAccessToken(null)
      set({ status: 'anonymous', user: null, orgs: [] })
    }
  },

  applyTokens: async (tokens: TokenPair) => {
    setAccessToken(tokens.access_token)
    setRefreshToken(tokens.refresh_token)
    await get().loadSession()
  },

  loadSession: async () => {
    const [me, orgs] = await Promise.all([
      request<{ data: User }>('/api/v1/auth/me'),
      request<{ data: OrgWithRole[] }>('/api/v1/orgs'),
    ])
    const stored = readActiveOrg()
    const active =
      stored && orgs.data.some((o) => o.slug === stored)
        ? stored
        : (orgs.data[0]?.slug ?? null)
    if (active) localStorage.setItem(ACTIVE_ORG_KEY, active)
    set({
      user: me.data,
      orgs: orgs.data,
      activeOrgSlug: active,
      status: 'authenticated',
    })
  },

  setActiveOrg: (slug: string) => {
    localStorage.setItem(ACTIVE_ORG_KEY, slug)
    set({ activeOrgSlug: slug })
  },

  logout: async () => {
    const refresh = getRefreshToken()
    if (refresh) {
      try {
        await request('/api/v1/auth/logout', {
          method: 'POST',
          body: { refresh_token: refresh },
        })
      } catch {
        // Logout is best-effort; clear local state regardless.
      }
    }
    setRefreshToken(null)
    setAccessToken(null)
    localStorage.removeItem(ACTIVE_ORG_KEY)
    set({ user: null, orgs: [], activeOrgSlug: null, status: 'anonymous' })
  },
}))

export function activeOrg(state: AuthState): OrgWithRole | null {
  return state.orgs.find((o) => o.slug === state.activeOrgSlug) ?? null
}
