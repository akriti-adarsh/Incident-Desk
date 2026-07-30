import { describe, expect, it } from 'vitest'

import { LEGAL_TRANSITIONS, formatBytes, formatDuration, relativeTime } from './format'

describe('formatDuration', () => {
  it('formats across units', () => {
    expect(formatDuration(null)).toBe('n/a')
    expect(formatDuration(30)).toBe('30s')
    expect(formatDuration(120)).toBe('2m')
    expect(formatDuration(5400)).toBe('1.5h')
    expect(formatDuration(172800)).toBe('2.0d')
  })
})

describe('relativeTime', () => {
  const now = new Date('2026-08-01T12:00:00Z')
  it('describes recent and older times', () => {
    expect(relativeTime('2026-08-01T11:59:40Z', now)).toBe('just now')
    expect(relativeTime('2026-08-01T11:30:00Z', now)).toBe('30m ago')
    expect(relativeTime('2026-08-01T09:00:00Z', now)).toBe('3h ago')
    expect(relativeTime('2026-07-30T12:00:00Z', now)).toBe('2d ago')
  })
})

describe('formatBytes', () => {
  it('scales', () => {
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(2048)).toBe('2.0 KB')
    expect(formatBytes(3 * 1024 * 1024)).toBe('3.0 MB')
  })
})

describe('state machine transitions', () => {
  it('matches the backend legal moves', () => {
    expect(LEGAL_TRANSITIONS.open).toEqual(['acknowledged'])
    expect(LEGAL_TRANSITIONS.acknowledged).toEqual(['mitigated', 'resolved'])
    expect(LEGAL_TRANSITIONS.postmortem).toEqual([])
  })
})
