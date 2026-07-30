import { act } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { toast, useTheme, useToasts } from './ui'

describe('theme store', () => {
  beforeEach(() => {
    localStorage.clear()
  })
  it('toggles and persists', () => {
    const start = useTheme.getState().theme
    act(() => useTheme.getState().toggle())
    const next = useTheme.getState().theme
    expect(next).not.toBe(start)
    expect(localStorage.getItem('incident_desk.theme')).toBe(next)
    expect(document.documentElement.getAttribute('data-theme')).toBe(next)
  })
})

describe('toast store', () => {
  beforeEach(() => {
    act(() => useToasts.setState({ toasts: [] }))
    vi.useFakeTimers()
  })
  it('pushes and auto-dismisses non-error toasts', () => {
    act(() => toast('success', 'saved'))
    expect(useToasts.getState().toasts).toHaveLength(1)
    act(() => vi.advanceTimersByTime(4001))
    expect(useToasts.getState().toasts).toHaveLength(0)
    vi.useRealTimers()
  })
  it('keeps error toasts until dismissed', () => {
    act(() => toast('error', 'boom', 'req-1'))
    const { toasts, dismiss } = useToasts.getState()
    expect(toasts[0]?.requestId).toBe('req-1')
    act(() => vi.advanceTimersByTime(10000))
    expect(useToasts.getState().toasts).toHaveLength(1)
    act(() => dismiss(toasts[0]!.id))
    expect(useToasts.getState().toasts).toHaveLength(0)
    vi.useRealTimers()
  })
})
