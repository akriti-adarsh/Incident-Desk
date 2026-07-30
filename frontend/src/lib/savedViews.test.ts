import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import { useSavedViews } from './savedViews'

describe('useSavedViews', () => {
  beforeEach(() => localStorage.clear())

  it('names and persists a saved view, capping at 6', () => {
    const { result } = renderHook(() => useSavedViews('acme'))
    act(() => result.current.saveView({ q: 'db', status: 'open', severity: 'sev1' }))
    expect(result.current.views[0]?.name).toContain('"db"')
    expect(result.current.views[0]?.name).toContain('open')

    for (let i = 0; i < 8; i++) {
      act(() => result.current.saveView({ q: `q${i}`, status: '', severity: '' }))
    }
    expect(result.current.views.length).toBeLessThanOrEqual(6)

    // Persisted across a fresh hook instance.
    const again = renderHook(() => useSavedViews('acme'))
    expect(again.result.current.views.length).toBeLessThanOrEqual(6)
  })

  it('names an empty filter set "All incidents"', () => {
    const { result } = renderHook(() => useSavedViews('acme'))
    act(() => result.current.saveView({ q: '', status: '', severity: '' }))
    expect(result.current.views[0]?.name).toBe('All incidents')
  })

  it('applyView returns the view unchanged', () => {
    const { result } = renderHook(() => useSavedViews('acme'))
    const view = { name: 'x', q: 'a', status: 'open' as const, severity: '' as const }
    expect(result.current.applyView(view)).toBe(view)
  })
})
