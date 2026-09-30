// Wave 2 edge cases: real-data shapes in the mock, error copy, slow parses and the HTTP client.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createHttpApi } from './http'
import { MockServer } from './mock/server'
import {
  ApiRequestError,
  PARSE_TIMEOUT_MS,
  errorMessage,
  isConflict,
  isParserTrouble,
  retryMinutes,
  withTimeout,
} from './types'

const fast = (failMode?: () => string | null) =>
  new MockServer({ parseLatencyMs: 0, ioLatencyMs: 0, now: () => Date.parse('2026-09-30T12:00:00Z'), failMode })

const err = (status: number, code: string, message: string) => new ApiRequestError(status, code, message)

describe('real-data edge cases in the mock', () => {
  it('messy_4 has a long brand, an unmatched red line, and a line with no generic', async () => {
    const o = await fast().createSampleOrder('messy_4')
    expect(o.status).toBe('pending_review')
    expect(o.items).toHaveLength(4)

    const long = o.items[0]
    expect(long.sku?.brand_name).toBe('Augmentin 625 Duo Tablet (Dispersible)')

    const unmatched = o.items[1]
    expect(unmatched.sku).toBeNull()
    expect(unmatched.confidence.triage).toBe('red')
    expect(unmatched.line_total_inr).toBe(0)
    expect(unmatched.confidence.reasons).toContain('no catalog match')

    const thyro = o.items[2]
    expect(thyro.sku?.sku_id).toBe('sku_thyronorm_50')
    expect(thyro.generic_alternative).toBeNull()

    const sum = o.items.reduce((a, i) => a + i.line_total_inr, 0)
    expect(o.total_inr).toBeCloseTo(sum, 2)
  })

  it('the unmatched line must be edited or removed before approval succeeds cleanly', async () => {
    const api = fast()
    const o = await api.createSampleOrder('messy_4')
    const v = await api.review(o.order_id, {
      decision: 'approve',
      items: [{ item_id: o.items[1].item_id, action: 'edit', sku_id: 'sku_okacet_10', quantity_packs: 1 }],
    })
    expect(v.status).toBe('verified')
    expect(v.items[1].sku?.sku_id).toBe('sku_okacet_10')
    expect(v.items[1].status).toBe('edited')
  })

  it('blank_0 parses to zero lines but still waits for a pharmacist', async () => {
    const api = fast()
    const o = await api.createSampleOrder('blank_0')
    expect(o.items).toEqual([])
    expect(o.total_inr).toBe(0)
    expect(o.status).toBe('pending_review')
    const row = (await api.getQueue()).find((q) => q.order_id === o.order_id)
    expect(row?.item_count).toBe(0)
    const r = await api.review(o.order_id, { decision: 'reject', note: 'Photo unreadable, please resend.' })
    expect(r.status).toBe('rejected')
  })

  it('lists the edge-case samples after the fixture samples', async () => {
    const ids = (await fast().listSamples()).map((s) => s.sample_id)
    expect(ids).toEqual(['typed_clinic_3', 'handwritten_2', 'messy_4', 'blank_0'])
  })

  it('typed Rx-only requests come back as needs_prescription', async () => {
    const o = await fast().createTextOrder('dolo, azithral 500')
    expect(o.status).toBe('needs_prescription')
    expect(o.items.find((i) => i.sku?.rx_only)?.sku?.brand_name).toBe('Azithral 500')
  })

  it.each([
    ['unsupported_image', 400],
    ['image_too_large', 413],
    ['rate_limited', 429],
    ['parser_failed', 502],
    ['parser_timeout', 504],
  ])('fail=%s → %i', async (code, status) => {
    const e = await fast(() => code)
      .createPrescriptionOrder(new Blob(['x'], { type: 'image/jpeg' }))
      .catch((x) => x)
    expect(e).toBeInstanceOf(ApiRequestError)
    expect(e.status).toBe(status)
    expect(e.code).toBe(code)
    expect(isParserTrouble(e)).toBe(true)
  })
})

describe('error copy', () => {
  it('shows the server message alone when there is one', () => {
    const server = 'We couldn’t open that image. Please take a new photo of the prescription and try again.'
    expect(errorMessage(err(400, 'unsupported_image', server))).toBe(server)
  })

  it('uses our own copy only when the server sent no message', () => {
    expect(errorMessage(err(400, 'unsupported_image', ''))).toMatch(/^That file isn’t a photo we can read/)
    expect(errorMessage(err(502, 'http_502', ''))).toMatch(/^We couldn’t read that prescription/)
  })

  it('429 shows the retry minutes from the message', () => {
    expect(retryMinutes('Parse limit reached. Try again in 23 minutes.')).toBe(23)
    expect(retryMinutes('Retry after 90 seconds')).toBe(2)
    expect(retryMinutes('Slow down')).toBeNull()
    expect(errorMessage(err(429, 'rate_limited', 'Try again in 1 min'))).toContain('Try again in 1 minute,')
    expect(errorMessage(err(429, 'rate_limited', 'Slow down'))).toBe('Slow down')
  })

  it('other codes show error.message verbatim', () => {
    for (const [s, c] of [
      [413, 'image_too_large'],
      [422, 'invalid_request'],
      [502, 'parser_failed'],
      [504, 'parser_timeout'],
      [409, 'invalid_transition'],
    ] as const) {
      expect(errorMessage(err(s, c, `msg ${s}`))).toBe(`msg ${s}`)
    }
  })

  it('409 is a conflict to reload, not parser trouble', () => {
    const e = err(409, 'invalid_transition', 'Already verified.')
    expect(isConflict(e)).toBe(true)
    expect(isParserTrouble(e)).toBe(false)
  })
})

describe('slow parses', () => {
  afterEach(() => vi.useRealTimers())

  it('gives up after 90 s with a sample-able 504', async () => {
    vi.useFakeTimers()
    const never = new Promise<never>(() => {})
    const p = withTimeout(never, PARSE_TIMEOUT_MS).catch((e) => e)
    await vi.advanceTimersByTimeAsync(PARSE_TIMEOUT_MS - 1)
    let settled = false
    void p.then(() => (settled = true))
    await Promise.resolve()
    expect(settled).toBe(false)
    await vi.advanceTimersByTimeAsync(1)
    const e = await p
    expect(e.status).toBe(504)
    expect(e.code).toBe('client_timeout')
    expect(isParserTrouble(e)).toBe(true)
  })

  it('a 20 s parse still resolves', async () => {
    vi.useFakeTimers()
    const slow = new MockServer({ parseLatencyMs: 20_000, ioLatencyMs: 0 })
    const p = withTimeout(slow.createSampleOrder('handwritten_2'), PARSE_TIMEOUT_MS)
    await vi.advanceTimersByTimeAsync(20_000)
    expect((await p).status).toBe('pending_review')
  })
})

describe('HTTP client', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('surfaces ErrorResponse.error.message', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ error: { code: 'not_found', message: 'Order not found.' } }), { status: 404 }),
      ),
    )
    const e = await createHttpApi('http://x').getOrder('nope').catch((x) => x)
    expect(e).toMatchObject({ status: 404, code: 'not_found', message: 'Order not found.' })
  })

  it('falls back to friendly copy when a proxy returns HTML', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('<html>413</html>', { status: 413 })))
    const e = await createHttpApi('http://x')
      .createPrescriptionOrder(new Blob(['x'], { type: 'image/jpeg' }))
      .catch((x) => x)
    expect(e).toMatchObject({ status: 413, message: 'That photo is over 5 MB. Try a smaller one.' })
  })

  it('maps an aborted upload to the client timeout error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new DOMException('timed out', 'TimeoutError')
      }),
    )
    const e = await createHttpApi('http://x').createSampleOrder('typed_clinic_3').catch((x) => x)
    expect(e).toMatchObject({ status: 504, code: 'client_timeout' })
  })

  it('builds URLs against the base without double slashes', async () => {
    const f = vi.fn(async () => new Response('[]', { status: 200 }))
    vi.stubGlobal('fetch', f)
    const api = createHttpApi('http://localhost:8000/')
    await api.searchCatalog('dolo 650', 50)
    expect((f.mock.calls[0] as unknown[])[0]).toBe('http://localhost:8000/api/catalog/search?q=dolo%20650&limit=20')
    expect(api.orderImageUrl('ord_1')).toBe('http://localhost:8000/api/orders/ord_1/image')
  })
})
