// Code review fixes: branch on error.code, OTC swaps, one outcome on a 409 place, resilient polling,
// and HTTP details (text-order abort, original filename).
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiRequestError, isConflict, isParserTrouble, type Order } from '../api/types'
import { resolveApiBase } from '../api/config'
import { createHttpApi } from '../api/http'
import { MockServer } from '../api/mock/server'
import { canSwap, placeOrder, pollWaiting, swapItem } from './actions'

const fast = () => new MockServer({ parseLatencyMs: 0, ioLatencyMs: 0, now: () => Date.parse('2026-09-30T12:00:00Z') })
const err = (status: number, code: string, message = 'server says') => new ApiRequestError(status, code, message)

describe('1. errors branch on error.code', () => {
  it('uses the code whatever the status', () => {
    expect(isParserTrouble(err(500, 'rate_limited'))).toBe(true)
    expect(isParserTrouble(err(500, 'parser_failed'))).toBe(true)
    expect(isParserTrouble(err(500, 'unsupported_image'))).toBe(true)
    expect(isConflict(err(400, 'invalid_transition'))).toBe(true)
  })

  it('does not infer a code from the status when the server sent one', () => {
    expect(isParserTrouble(err(400, 'invalid_request'))).toBe(false)
    expect(isParserTrouble(err(504, 'not_found'))).toBe(false)
    expect(isConflict(err(409, 'not_found'))).toBe(false)
  })

  it('falls back to the status only for uncoded (non-JSON) errors', () => {
    expect(isParserTrouble(err(502, 'http_502', ''))).toBe(true)
    expect(isParserTrouble(err(500, 'http_500', ''))).toBe(false)
    expect(isConflict(err(409, 'http_409', ''))).toBe(true)
  })
})

describe('3. swaps on confirmed OTC carts', () => {
  const order = (status: Order['status']) => ({ status }) as Order

  it('allows swapping in pending_review and confirmed_otc only', () => {
    expect(canSwap(order('pending_review'))).toBe(true)
    expect(canSwap(order('confirmed_otc'))).toBe(true)
    for (const s of ['verified', 'rejected', 'needs_prescription', 'placed'] as const) expect(canSwap(order(s))).toBe(false)
  })

  it('swaps a typed OTC line to its generic and back', async () => {
    const api = fast()
    const o = await api.createTextOrder('dolo')
    expect(o.status).toBe('confirmed_otc')
    const line = o.items[0]
    expect(line.generic_alternative).not.toBeNull()
    const on = await swapItem(api, o.order_id, line.item_id, true)
    expect(on.applied).toBe(true)
    expect(on.order.items[0].sku?.sku_id).toBe(line.generic_alternative?.sku_id)
    expect(on.order.total_inr).toBeLessThan(o.total_inr)
    const off = await swapItem(api, o.order_id, line.item_id, false)
    expect(off.order.items[0].sku?.sku_id).toBe(line.sku?.sku_id)
  })
})

describe('4. place after a 409 gives one outcome, the reloaded order', () => {
  it('places a verified order', async () => {
    const api = fast()
    const o = await api.createSampleOrder('typed_clinic_3')
    await api.review(o.order_id, { decision: 'approve' })
    const r = await placeOrder(api, o.order_id)
    expect(r).toMatchObject({ applied: true, order: { status: 'placed' } })
  })

  it('placing twice reloads instead of throwing', async () => {
    const api = fast()
    const o = await api.createSampleOrder('typed_clinic_3')
    await api.review(o.order_id, { decision: 'approve' })
    await placeOrder(api, o.order_id)
    const again = await placeOrder(api, o.order_id)
    expect(again).toMatchObject({ applied: false, order: { status: 'placed' } })
  })

  it('placing an order still in review returns its current state', async () => {
    const api = fast()
    const o = await api.createSampleOrder('typed_clinic_3')
    const r = await placeOrder(api, o.order_id)
    expect(r).toMatchObject({ applied: false, order: { status: 'pending_review' } })
  })

  it('a swap after review reloads the reviewed order', async () => {
    const api = fast()
    const o = await api.createSampleOrder('typed_clinic_3')
    await api.review(o.order_id, { decision: 'approve' })
    const r = await swapItem(api, o.order_id, 'itm_1', true)
    expect(r).toMatchObject({ applied: false, order: { status: 'verified' } })
  })

  it('other errors still throw', async () => {
    const api = fast()
    await expect(placeOrder(api, 'ord_missing')).rejects.toMatchObject({ code: 'not_found' })
  })
})

describe('5. polling survives one failed request', () => {
  it('still reports the other orders that changed', async () => {
    const api = fast()
    const a = await api.createSampleOrder('typed_clinic_3')
    const b = await api.createSampleOrder('handwritten_2')
    const c = await api.createSampleOrder('typed_clinic_3')
    await api.review(c.order_id, { decision: 'reject', note: 'Too old.' })
    await api.review(b.order_id, { decision: 'approve' })
    const failing = {
      getOrder: (id: string) => (id === a.order_id ? Promise.reject(new TypeError('network')) : api.getOrder(id)),
    }
    const errors: string[] = []
    const changed = await pollWaiting(failing, [a, b, c], (id) => errors.push(id))
    expect(errors).toEqual([a.order_id])
    expect(changed.map((x) => [x.after.order_id, x.after.status])).toEqual([
      [b.order_id, 'verified'],
      [c.order_id, 'rejected'],
    ])
  })

  it('reports nothing when nothing changed', async () => {
    const api = fast()
    const a = await api.createSampleOrder('typed_clinic_3')
    expect(await pollWaiting(api, [a])).toEqual([])
  })
})

describe('7. API base URL', () => {
  it('defaults to localhost only in dev', () => {
    expect(resolveApiBase({ DEV: true, mocks: false })).toEqual({ baseUrl: 'http://localhost:8000', error: null })
    const prod = resolveApiBase({ DEV: false, mocks: false })
    expect(prod.baseUrl).toBe('')
    expect(prod.error).toMatch(/VITE_API_BASE_URL/)
    expect(resolveApiBase({ DEV: false, mocks: false, VITE_API_BASE_URL: 'https://rio-api.buildspacelabs.com' })).toEqual({
      baseUrl: 'https://rio-api.buildspacelabs.com',
      error: null,
    })
    expect(resolveApiBase({ DEV: false, mocks: true }).error).toBeNull()
  })
})

describe('HTTP client details', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('6. text orders carry an abort signal and map an abort to the client timeout', async () => {
    const f = vi.fn(async (_url: string, init?: RequestInit) => {
      expect(init?.signal).toBeInstanceOf(AbortSignal)
      throw new DOMException('timed out', 'TimeoutError')
    })
    vi.stubGlobal('fetch', f)
    const e = await createHttpApi('http://x').createTextOrder('dolo').catch((x) => x)
    expect(f).toHaveBeenCalledOnce()
    expect(e).toMatchObject({ status: 504, code: 'client_timeout' })
  })

  it('8. an unresized upload keeps its own filename and type', async () => {
    let sent: File | null = null
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, init?: RequestInit) => {
        sent = (init?.body as FormData).get('image') as File
        return new Response('{}', { status: 200 })
      }),
    )
    const api = createHttpApi('http://x')
    await api.createPrescriptionOrder(new File(['x'], 'IMG_2231.png', { type: 'image/png' }))
    expect(sent!.name).toBe('IMG_2231.png')
    expect(sent!.type).toBe('image/png')
    await api.createPrescriptionOrder(new Blob(['x'], { type: 'image/jpeg' }))
    expect(sent!.name).toBe('prescription.jpg')
  })
})
