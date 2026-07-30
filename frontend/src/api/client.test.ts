import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  ApiError,
  getRefreshToken,
  request,
  setAccessToken,
  setRefreshToken,
} from './client'

describe('api client', () => {
  beforeEach(() => {
    localStorage.clear()
    setAccessToken(null)
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('stores and clears the refresh token', () => {
    setRefreshToken('r1')
    expect(getRefreshToken()).toBe('r1')
    setRefreshToken(null)
    expect(getRefreshToken()).toBeNull()
  })

  it('attaches the bearer token and parses the envelope', async () => {
    setAccessToken('access-1')
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ data: { ok: true } }), { status: 200 }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await request<{ data: { ok: boolean } }>('/api/v1/x')
    expect(result.data.ok).toBe(true)
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit
    const headers = init.headers as Record<string, string>
    expect(headers.Authorization).toBe('Bearer access-1')
  })

  it('raises a typed ApiError carrying code and request id', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ error: { code: 'conflict', message: 'nope', request_id: 'req-9' } }),
          { status: 409 },
        ),
      ),
    )
    await expect(request('/api/v1/x')).rejects.toMatchObject({
      status: 409,
      code: 'conflict',
      requestId: 'req-9',
    })
  })

  it('refreshes once on 401 then retries', async () => {
    setAccessToken('stale')
    setRefreshToken('refresh-1')
    const fetchMock = vi
      .fn()
      // first call: 401
      .mockResolvedValueOnce(new Response('{"error":{"code":"unauthorized","message":"x","request_id":"r"}}', { status: 401 }))
      // refresh call: new tokens
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ data: { access_token: 'fresh', refresh_token: 'refresh-2' } }), {
          status: 200,
        }),
      )
      // retry: success
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: 'ok' }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await request<{ data: string }>('/api/v1/x')
    expect(result.data).toBe('ok')
    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(getRefreshToken()).toBe('refresh-2')
  })

  it('is an ApiError instance', () => {
    const err = new ApiError(404, { error: { code: 'not_found', message: 'gone', request_id: 'r' } })
    expect(err).toBeInstanceOf(Error)
    expect(err.status).toBe(404)
  })
})
