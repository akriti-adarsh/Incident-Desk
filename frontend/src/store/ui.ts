// Small client-only UI state: theme and toasts.

import { create } from 'zustand'

type Theme = 'dark' | 'light'
const THEME_KEY = 'incident_desk.theme'

function initialTheme(): Theme {
  const stored = localStorage.getItem(THEME_KEY)
  if (stored === 'light' || stored === 'dark') return stored
  return 'dark'
}

interface ThemeState {
  theme: Theme
  toggle: () => void
}

export const useTheme = create<ThemeState>((set, get) => ({
  theme: initialTheme(),
  toggle: () => {
    const next = get().theme === 'dark' ? 'light' : 'dark'
    localStorage.setItem(THEME_KEY, next)
    document.documentElement.setAttribute('data-theme', next)
    set({ theme: next })
  },
}))

export interface Toast {
  id: number
  kind: 'success' | 'error' | 'info'
  message: string
  requestId?: string
}

interface ToastState {
  toasts: Toast[]
  push: (kind: Toast['kind'], message: string, requestId?: string) => void
  dismiss: (id: number) => void
}

let nextId = 1

export const useToasts = create<ToastState>((set) => ({
  toasts: [],
  push: (kind, message, requestId) => {
    const id = nextId++
    set((s) => ({ toasts: [...s.toasts, { id, kind, message, requestId }] }))
    if (kind !== 'error') {
      setTimeout(() => {
        set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }))
      }, 4000)
    }
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}))

export function toast(kind: Toast['kind'], message: string, requestId?: string): void {
  useToasts.getState().push(kind, message, requestId)
}
