import { beforeEach, describe, expect, it } from 'vitest'
import type { CartItem } from '../../contracts.gen'
import { FORECAST_NOW_INDEX } from './forecast'
import type { KeyValueStore } from './server'
import { MockServer, worstTriage } from './server'

const FIXED_TIME = Date.parse('2026-09-29T19:00:00+05:30')
const jpeg = () => new Blob(['x'], { type: 'image/jpeg' })

function memStore(): KeyValueStore {
  let data: string | null = null
  return {
    get: () => data,
    set: (v) => {
      data = v
    },
    clear: () => {
      data = null
    },
  }
}

function makeServer(opts: Partial<ConstructorParameters<typeof MockServer>[0]> = {}) {
  return new MockServer({ parseLatencyMs: 0, ioLatencyMs: 0, now: () => FIXED_TIME, ...opts })
}

describe('worstTriage', () => {
  it('ignores removed items when picking the worst triage', () => {
    const base = {
      parsed: null,
      requested_text: null,
      sku: null,
      quantity_packs: 1,
      unit_price_inr: 0,
      line_total_inr: 0,
      generic_alternative: null,
      savings_inr: null,
    }
    const items: CartItem[] = [
      {
        ...base,
        item_id: 'itm_1',
        status: 'removed',
        confidence: { score: 0, match_score: 0, completeness: 1, legibility: 1, triage: 'red', reasons: [] },
      },
      {
        ...base,
        item_id: 'itm_2',
        status: 'approved',
        confidence: { score: 1, match_score: 1, completeness: 1, legibility: 1, triage: 'green', reasons: [] },
      },
    ]
    expect(worstTriage(items)).toBe('green')
  })
})

describe('MockServer seeded queue', () => {
  let server: MockServer

  beforeEach(() => {
    server = makeServer()
  })

  it('contains only pending orders, worst triage first then oldest', async () => {
    const queue = await server.getQueue()
    expect(queue.map((q) => q.order_id)).toEqual(['ord_demo_pending', 'ord_seed_green'])
    expect(queue[0].worst_triage).toBe('red')
    expect(queue[1].worst_triage).toBe('green')
  })

  it('reports the seeded pending order correctly', async () => {
    const queue = await server.getQueue()
    const demo = queue.find((q) => q.order_id === 'ord_demo_pending')!
    expect(demo.item_count).toBe(3)
    expect(demo.total_inr).toBe(412.1)
    expect(demo.counts).toEqual({ green: 1, amber: 1, red: 1 })
  })
})

describe('createSampleOrder', () => {
  let server: MockServer

  beforeEach(() => {
    server = makeServer()
  })

  it('creates a pending-review order from a known sample and adds it to the queue', async () => {
    const order = await server.createSampleOrder('typed_clinic_3')
    expect(order.status).toBe('pending_review')
    expect(order.requires_review).toBe(true)
    expect(order.items).toHaveLength(3)
    expect(order.total_inr).toBe(412.1)

    const queue = await server.getQueue()
    expect(queue.map((q) => q.order_id)).toContain(order.order_id)
  })

  it('404s for an unknown sample id', async () => {
    await expect(server.createSampleOrder('does_not_exist')).rejects.toMatchObject({
      status: 404,
      code: 'not_found',
    })
  })
})

describe('createPrescriptionOrder', () => {
  it('creates a pending-review order for a valid image', async () => {
    const server = makeServer()
    const order = await server.createPrescriptionOrder(jpeg())
    expect(order.status).toBe('pending_review')
    expect(order.requires_review).toBe(true)
  })

  it('surfaces parser_failed as a 502', async () => {
    const server = makeServer({ failMode: () => 'parser_failed' })
    await expect(server.createPrescriptionOrder(jpeg())).rejects.toMatchObject({
      status: 502,
      code: 'parser_failed',
    })
  })

  it('surfaces parser_timeout as a 504', async () => {
    const server = makeServer({ failMode: () => 'parser_timeout' })
    await expect(server.createPrescriptionOrder(jpeg())).rejects.toMatchObject({
      status: 504,
      code: 'parser_timeout',
    })
  })

  it('surfaces rate_limited as a 429', async () => {
    const server = makeServer({ failMode: () => 'rate_limited' })
    await expect(server.createPrescriptionOrder(jpeg())).rejects.toMatchObject({
      status: 429,
      code: 'rate_limited',
    })
  })

  it('rejects an unsupported image type with 400 unsupported_image', async () => {
    const server = makeServer()
    const gif = new Blob(['x'], { type: 'image/gif' })
    await expect(server.createPrescriptionOrder(gif)).rejects.toMatchObject({
      status: 400,
      code: 'unsupported_image',
    })
  })
})

describe('swap', () => {
  let server: MockServer

  beforeEach(() => {
    server = makeServer()
  })

  it('switches the Augmentin line to its generic and lowers the total by the savings', async () => {
    const before = await server.getOrder('ord_demo_pending')
    const augmentin = before.items.find((i) => i.generic_alternative)!
    expect(augmentin.sku?.sku_id).toBe('sku_augmentin_625')

    const after = await server.swap('ord_demo_pending', { item_id: augmentin.item_id, use_generic: true })
    const swapped = after.items.find((i) => i.item_id === augmentin.item_id)!
    expect(swapped.sku?.sku_id).toBe('sku_moxclav_625')
    expect(after.total_inr).toBe(before.total_inr - (augmentin.savings_inr ?? 0))
  })

  it('restores the original sku when use_generic is set back to false', async () => {
    const augmentin = (await server.getOrder('ord_demo_pending')).items.find((i) => i.generic_alternative)!
    await server.swap('ord_demo_pending', { item_id: augmentin.item_id, use_generic: true })
    const restored = await server.swap('ord_demo_pending', { item_id: augmentin.item_id, use_generic: false })
    const item = restored.items.find((i) => i.item_id === augmentin.item_id)!
    expect(item.sku?.sku_id).toBe('sku_augmentin_625')
    expect(restored.total_inr).toBe(412.1)
  })

  it('409s once the order has been reviewed', async () => {
    const order = await server.getOrder('ord_demo_pending')
    const item = order.items[0]
    await server.review('ord_demo_pending', { decision: 'approve', items: [] })
    await expect(server.swap('ord_demo_pending', { item_id: item.item_id, use_generic: true })).rejects.toMatchObject(
      { status: 409, code: 'invalid_transition' },
    )
  })
})

describe('review: approve', () => {
  let server: MockServer

  beforeEach(() => {
    server = makeServer()
  })

  it('approving with no item decisions approves every item and verifies the order', async () => {
    const order = await server.review('ord_demo_pending', { decision: 'approve', items: [] })
    expect(order.status).toBe('verified')
    expect(order.items.every((i) => i.status === 'approved')).toBe(true)
    expect(order.reviewed_at).not.toBeNull()

    const queue = await server.getQueue()
    expect(queue.map((q) => q.order_id)).not.toContain('ord_demo_pending')

    const fetched = await server.getOrder('ord_demo_pending')
    expect(fetched.status).toBe('verified')
  })

  it('edits a line to another SKU and quantity, recomputing the total', async () => {
    const before = await server.getOrder('ord_demo_pending')
    const augmentinLine = before.items.find((i) => i.sku?.sku_id === 'sku_augmentin_625')!
    const order = await server.review('ord_demo_pending', {
      decision: 'approve',
      items: [{ item_id: augmentinLine.item_id, action: 'edit', sku_id: 'sku_crocin_650', quantity_packs: 2 }],
    })
    const edited = order.items.find((i) => i.item_id === augmentinLine.item_id)!
    expect(edited.status).toBe('edited')
    expect(edited.sku?.sku_id).toBe('sku_crocin_650')
    expect(edited.quantity_packs).toBe(2)
    expect(edited.line_total_inr).toBe(edited.sku!.mrp_inr * 2)
    expect(order.total_inr).toBe(sumOf(order.items))
  })

  it('removes a line so it is excluded from the total', async () => {
    const before = await server.getOrder('ord_demo_pending')
    const target = before.items[0]
    const order = await server.review('ord_demo_pending', {
      decision: 'approve',
      items: [{ item_id: target.item_id, action: 'remove' }],
    })
    const removed = order.items.find((i) => i.item_id === target.item_id)!
    expect(removed.status).toBe('removed')
    expect(order.total_inr).toBe(sumOf(order.items))
  })

  it('404s for an unknown item id', async () => {
    await expect(
      server.review('ord_demo_pending', { decision: 'approve', items: [{ item_id: 'itm_nope', action: 'remove' }] }),
    ).rejects.toMatchObject({ status: 404, code: 'not_found' })
  })

  it('409s when the order has already been reviewed', async () => {
    await server.review('ord_demo_pending', { decision: 'approve', items: [] })
    await expect(server.review('ord_demo_pending', { decision: 'approve', items: [] })).rejects.toMatchObject({
      status: 409,
      code: 'invalid_transition',
    })
  })

  it('422s when every line is removed', async () => {
    const before = await server.getOrder('ord_demo_pending')
    const items = before.items.map((i) => ({ item_id: i.item_id, action: 'remove' as const }))
    await expect(server.review('ord_demo_pending', { decision: 'approve', items })).rejects.toMatchObject({
      status: 422,
      code: 'invalid_request',
    })
  })
})

describe('review: reject', () => {
  let server: MockServer

  beforeEach(() => {
    server = makeServer()
  })

  it('422s without a note', async () => {
    await expect(server.review('ord_demo_pending', { decision: 'reject' })).rejects.toMatchObject({
      status: 422,
      code: 'invalid_request',
    })
  })

  it('rejects with a note', async () => {
    const order = await server.review('ord_demo_pending', { decision: 'reject', note: 'Illegible handwriting' })
    expect(order.status).toBe('rejected')
    expect(order.pharmacist_note).toBe('Illegible handwriting')
  })
})

describe('place', () => {
  let server: MockServer

  beforeEach(() => {
    server = makeServer()
  })

  it('places a verified order', async () => {
    await server.review('ord_demo_pending', { decision: 'approve', items: [] })
    const order = await server.place('ord_demo_pending')
    expect(order.status).toBe('placed')
  })

  it('409s for a pending_review order', async () => {
    await expect(server.place('ord_demo_pending')).rejects.toMatchObject({ status: 409, code: 'invalid_transition' })
  })

  it('places a confirmed_otc order', async () => {
    const otc = await server.createTextOrder('dolo, ORS')
    const order = await server.place(otc.order_id)
    expect(order.status).toBe('placed')
  })
})

describe('createTextOrder', () => {
  let server: MockServer

  beforeEach(() => {
    server = makeServer()
  })

  it('"dolo, ORS" resolves to a confirmed OTC order', async () => {
    const order = await server.createTextOrder('dolo, ORS')
    expect(order.status).toBe('confirmed_otc')
    expect(order.requires_review).toBe(false)
    expect(order.items).toHaveLength(2)
    expect(order.total_inr).toBe(55.6)
  })

  it('"augmentin" needs a prescription', async () => {
    const order = await server.createTextOrder('augmentin')
    expect(order.status).toBe('needs_prescription')
    expect(order.requires_review).toBe(true)
  })

  it('422s for gibberish that matches nothing', async () => {
    await expect(server.createTextOrder('zzqqxx')).rejects.toMatchObject({ status: 422, code: 'invalid_request' })
  })

  it('reads a leading quantity, e.g. "2 dolo"', async () => {
    const order = await server.createTextOrder('2 dolo')
    expect(order.items[0].quantity_packs).toBe(2)
  })
})

describe('persistence across instances', () => {
  it('shares state through a common store and reset() restores the seed', async () => {
    const store = memStore()
    const a = new MockServer({ parseLatencyMs: 0, ioLatencyMs: 0, now: () => FIXED_TIME, store })
    const created = await a.createSampleOrder('typed_clinic_3')

    const b = new MockServer({ parseLatencyMs: 0, ioLatencyMs: 0, now: () => FIXED_TIME, store })
    const seenByB = await b.getOrder(created.order_id)
    expect(seenByB.order_id).toBe(created.order_id)

    b.reset()
    const queueAfterReset = await b.getQueue()
    expect(queueAfterReset.map((q) => q.order_id).sort()).toEqual(['ord_demo_pending', 'ord_seed_green'])
    await expect(b.getOrder(created.order_id)).rejects.toMatchObject({ status: 404, code: 'not_found' })
  })
})

describe('forecast', () => {
  let server: MockServer

  beforeEach(() => {
    server = makeServer()
  })

  it('returns actuals up to now and nulls after for a known sku/area', async () => {
    const series = await server.skuForecast('sku_dolo_650', 'Area A')
    const actualPoints = series.points.filter((p) => p.actual != null)
    const nullPoints = series.points.filter((p) => p.actual == null)
    expect(actualPoints).toHaveLength(FORECAST_NOW_INDEX + 1)
    expect(nullPoints.length).toBeGreaterThan(0)
    expect(series.points.slice(0, FORECAST_NOW_INDEX + 1).every((p) => p.actual != null)).toBe(true)
    expect(series.points.slice(FORECAST_NOW_INDEX + 1).every((p) => p.actual == null)).toBe(true)
  })

  it('404s for an unknown sku', async () => {
    await expect(server.skuForecast('sku_does_not_exist', 'Area A')).rejects.toMatchObject({
      status: 404,
      code: 'not_found',
    })
  })

  it('summary reorders sort stockout risks first', async () => {
    const summary = await server.forecastSummary()
    const risky = summary.reorders.filter((r) => r.stockout_risk)
    const firstNonRisky = summary.reorders.findIndex((r) => !r.stockout_risk)
    if (firstNonRisky >= 0) {
      // Once a non-risky entry appears, no risky entry should follow it.
      expect(summary.reorders.slice(firstNonRisky).every((r) => !r.stockout_risk)).toBe(true)
    }
    expect(risky.length).toBeGreaterThanOrEqual(0)
  })
})

function sumOf(items: { status: string; line_total_inr: number }[]): number {
  const total = items.filter((i) => i.status !== 'removed').reduce((acc, i) => acc + Math.round(i.line_total_inr * 100), 0) / 100
  return Math.round(total * 100) / 100
}
