// In-browser mock of the Rio API (VITE_MOCKS=1). It keeps real state so the whole demo
// works without a backend: create → pending_review (after fake parse latency), pharmacist
// review → verified/rejected, typed orders → confirmed_otc/needs_prescription, swap, place.
// State is mirrored to localStorage so /chat and /pharmacist in two tabs see the same orders.
import type {
  CartItem,
  ItemDecision,
  Order,
  QueueItem,
  ReviewRequest,
  Sample,
  SKU,
  SwapRequest,
} from '../../contracts.gen'
import samplesFixture from '../../../../contracts/fixtures/samples.json'
import { ApiRequestError, type RioApi, type Triage } from '../types'
import { findSku, searchCatalog } from './catalog'
import { forecastSummary, synthSeries } from './forecast'
import { FALLBACK_IMAGE, SAMPLE_IMAGES } from './images'
import { PENDING_FIXTURE, greenSeed, priceOrder, sampleParse, type OrderSeed } from './orders'

export interface KeyValueStore {
  get(): string | null
  set(value: string): void
  clear(): void
}

export interface MockOptions {
  /** Fake parse latency for prescription/sample orders, ms. */
  parseLatencyMs?: number
  /** Latency for every other call, ms. */
  ioLatencyMs?: number
  now?: () => number
  store?: KeyValueStore
  /** Return an error code to make the next prescription upload fail (parser_failed, parser_timeout, rate_limited). */
  failMode?: () => string | null
}

interface MockState {
  seq: number
  orders: Record<string, Order>
  /** order_id → sample id whose image this order shows. */
  imageOf: Record<string, string>
  /** `${order_id}/${item_id}` → the SKU before the customer swapped to the generic. */
  preSwap: Record<string, SKU>
}

const TRIAGE_RANK: Record<Triage, number> = { red: 0, amber: 1, green: 2 }
const FAILS: Record<string, [number, string]> = {
  parser_failed: [502, 'We couldn’t read that photo. Try a sharper, well-lit picture, or try a sample.'],
  parser_timeout: [504, 'Reading the prescription took too long. Try again, or try a sample.'],
  rate_limited: [429, 'Parse limit reached for this IP. Try again in 23 minutes.'],
  unsupported_image: [400, 'Could not decode the upload as jpeg, png or webp.'],
  image_too_large: [413, 'That photo is over 5 MB. Try a smaller one.'],
}

/** Mock-only samples that exercise real-data edge cases. */
const EDGE_SAMPLES: Sample[] = [
  { sample_id: 'messy_4', label: 'Messy Rx, 4 lines (edge cases)', thumbnail_url: '/api/samples/messy_4/image' },
  { sample_id: 'blank_0', label: 'Blurry photo, nothing readable', thumbnail_url: '/api/samples/blank_0/image' },
]

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T
const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))

function notFound(what: string): never {
  throw new ApiRequestError(404, 'not_found', `${what} not found.`)
}

function invalid(message: string): never {
  throw new ApiRequestError(422, 'invalid_request', message)
}

export function worstTriage(items: CartItem[]): Triage {
  let worst: Triage = 'green'
  for (const i of items) {
    if (i.status === 'removed') continue
    if (TRIAGE_RANK[i.confidence.triage] < TRIAGE_RANK[worst]) worst = i.confidence.triage
  }
  return worst
}

export class MockServer implements RioApi {
  readonly isMock = true
  private state: MockState
  private readonly opts: Required<Omit<MockOptions, 'store' | 'failMode'>> & Pick<MockOptions, 'store' | 'failMode'>
  private readonly uploads = new Map<string, string>()

  constructor(options: MockOptions = {}) {
    this.opts = {
      parseLatencyMs: options.parseLatencyMs ?? 2000,
      ioLatencyMs: options.ioLatencyMs ?? 120,
      now: options.now ?? Date.now,
      store: options.store,
      failMode: options.failMode,
    }
    this.state = this.load() ?? this.seed()
  }

  // ---------- state ----------

  private seed(): MockState {
    const now = this.opts.now()
    const pending: Order = {
      ...clone(PENDING_FIXTURE),
      created_at: new Date(now - 6 * 60_000).toISOString(),
    }
    const green = this.orderFrom('ord_seed_green', greenSeed(), 'prescription', now - 3 * 60_000)
    const state: MockState = {
      seq: 100,
      orders: { [pending.order_id]: pending, [green.order_id]: green },
      imageOf: { [pending.order_id]: 'typed_clinic_3', [green.order_id]: 'typed_clinic_3' },
      preSwap: {},
    }
    this.persist(state)
    return state
  }

  private load(): MockState | null {
    try {
      const raw = this.opts.store?.get()
      return raw ? (JSON.parse(raw) as MockState) : null
    } catch {
      return null
    }
  }

  private persist(state = this.state) {
    try {
      this.opts.store?.set(JSON.stringify(state))
    } catch {
      /* storage full or blocked: memory state still works */
    }
  }

  /** Pick up writes from another tab before each call. */
  private sync() {
    const fresh = this.load()
    if (fresh) this.state = fresh
  }

  reset() {
    try {
      this.opts.store?.clear()
    } catch {
      /* ignore */
    }
    this.uploads.clear()
    this.state = this.seed()
  }

  private nextId(prefix: string) {
    this.state.seq += 1
    return `${prefix}_${this.state.seq.toString(36)}${Math.floor(Math.random() * 1296).toString(36).padStart(2, '0')}`
  }

  private orderFrom(orderId: string, seed: OrderSeed, source: Order['source'], at: number): Order {
    return priceOrder({
      order_id: orderId,
      created_at: new Date(at).toISOString(),
      source,
      status: 'pending_review',
      has_image: true,
      parsed_rx: seed.parsed_rx,
      items: seed.items,
      total_inr: 0,
      requires_review: true,
      pharmacist_note: null,
      reviewed_at: null,
    })
  }

  private get(orderId: string): Order {
    return this.state.orders[orderId] ?? notFound('Order')
  }

  private save(order: Order): Order {
    const priced = priceOrder(order)
    this.state.orders[priced.order_id] = priced
    this.persist()
    return clone(priced)
  }

  private io() {
    return sleep(this.opts.ioLatencyMs)
  }

  // ---------- customer ----------

  async createPrescriptionOrder(image: Blob): Promise<Order> {
    const fail = this.opts.failMode?.()
    await sleep(this.opts.parseLatencyMs)
    if (fail && FAILS[fail]) {
      const [status, message] = FAILS[fail]
      throw new ApiRequestError(status, fail, message)
    }
    if (image.size > 5 * 1024 * 1024) {
      throw new ApiRequestError(413, 'image_too_large', 'That photo is over 5 MB. Try a smaller one.')
    }
    if (image.type && !/^image\/(jpeg|png|webp)$/.test(image.type)) {
      throw new ApiRequestError(400, 'unsupported_image', 'Send a JPEG, PNG or WebP photo.')
    }
    this.sync()
    const order = this.orderFrom(this.nextId('ord'), sampleParse('typed_clinic_3')!, 'prescription', this.opts.now())
    this.state.imageOf[order.order_id] = 'typed_clinic_3'
    try {
      if (typeof URL.createObjectURL === 'function') this.uploads.set(order.order_id, URL.createObjectURL(image))
    } catch {
      /* non-browser: fall back to the sample image */
    }
    return this.save(order)
  }

  async createSampleOrder(sampleId: string): Promise<Order> {
    const seed = sampleParse(sampleId) ?? notFound('Sample')
    await sleep(this.opts.parseLatencyMs)
    this.sync()
    const order = this.orderFrom(this.nextId('ord'), seed, 'sample', this.opts.now())
    this.state.imageOf[order.order_id] = sampleId
    return this.save(order)
  }

  async createTextOrder(text: string): Promise<Order> {
    await sleep(Math.max(this.opts.ioLatencyMs, Math.min(this.opts.parseLatencyMs, 700)))
    this.sync()
    const requests = text
      .split(/,|;|\n|\+|\band\b|&/i)
      .map((t) => t.trim())
      .filter(Boolean)
      .slice(0, 12)
    if (requests.length === 0) invalid('Type the medicines you need, for example “Dolo 650, ORS”.')
    const items: CartItem[] = requests.map((req, idx) => {
      const m = /^(\d{1,2})\s*(?:x|strips?|packs?|of)?\s*(.+)$/i.exec(req)
      const qty = m ? Math.max(1, parseInt(m[1], 10)) : 1
      const name = m ? m[2] : req
      const best = searchCatalog(name, 1)[0]
      const hit = best && best.score >= 0.5 ? best : null
      return {
        item_id: `itm_t${idx + 1}`,
        parsed: null,
        requested_text: req,
        sku: hit?.sku ?? null,
        quantity_packs: qty,
        unit_price_inr: 0,
        line_total_inr: 0,
        generic_alternative: null,
        savings_inr: null,
        confidence: {
          score: hit?.score ?? 0,
          match_score: hit?.score ?? 0,
          completeness: 1,
          legibility: 1,
          triage: !hit ? 'red' : hit.score >= 0.85 ? 'green' : 'amber',
          reasons: hit ? [] : ['not found in catalog'],
        },
        status: hit ? 'approved' : 'removed',
      }
    })
    if (items.every((i) => !i.sku)) {
      invalid(`Couldn’t find “${requests.join(', ')}” in our catalog. Try a brand name like Dolo 650.`)
    }
    const needsRx = items.some((i) => i.sku?.rx_only)
    const order: Order = {
      order_id: this.nextId('ord'),
      created_at: new Date(this.opts.now()).toISOString(),
      source: 'text',
      status: needsRx ? 'needs_prescription' : 'confirmed_otc',
      has_image: false,
      parsed_rx: null,
      items: needsRx ? items.map((i) => (i.sku ? { ...i, status: 'pending' as const } : i)) : items,
      total_inr: 0,
      requires_review: needsRx,
      pharmacist_note: null,
      reviewed_at: null,
    }
    return this.save(order)
  }

  async getOrder(orderId: string): Promise<Order> {
    await this.io()
    this.sync()
    return clone(this.get(orderId))
  }

  orderImageUrl(orderId: string): string {
    const upload = this.uploads.get(orderId)
    if (upload) return upload
    const sample = this.state.imageOf[orderId]
    return (sample && SAMPLE_IMAGES[sample]) || FALLBACK_IMAGE
  }

  async swap(orderId: string, body: SwapRequest): Promise<Order> {
    await this.io()
    this.sync()
    const order = this.get(orderId)
    if (order.status !== 'pending_review') {
      throw new ApiRequestError(409, 'invalid_transition', 'This order has already been reviewed, so it can’t be changed.')
    }
    const item = order.items.find((i) => i.item_id === body.item_id) ?? notFound('Item')
    const key = `${orderId}/${item.item_id}`
    if (body.use_generic) {
      if (!item.generic_alternative || !item.sku) invalid('This medicine has no cheaper generic.')
      if (item.sku.sku_id !== item.generic_alternative.sku_id) {
        this.state.preSwap[key] = item.sku
        item.sku = item.generic_alternative
      }
    } else if (this.state.preSwap[key]) {
      item.sku = this.state.preSwap[key]
      delete this.state.preSwap[key]
    }
    return this.save(order)
  }

  async place(orderId: string): Promise<Order> {
    await this.io()
    this.sync()
    const order = this.get(orderId)
    if (order.status !== 'verified' && order.status !== 'confirmed_otc') {
      throw new ApiRequestError(409, 'invalid_transition', `An order that is ${order.status.replace('_', ' ')} can’t be placed.`)
    }
    return this.save({ ...order, status: 'placed' })
  }

  async listSamples(): Promise<Sample[]> {
    await this.io()
    return [...clone(samplesFixture as Sample[]), ...EDGE_SAMPLES]
  }

  sampleImageUrl(sampleId: string): string {
    return SAMPLE_IMAGES[sampleId] ?? FALLBACK_IMAGE
  }

  // ---------- pharmacist ----------

  async getQueue(): Promise<QueueItem[]> {
    await this.io()
    this.sync()
    return Object.values(this.state.orders)
      .filter((o) => o.status === 'pending_review')
      .map((o): QueueItem => {
        const live = o.items.filter((i) => i.status !== 'removed')
        const counts = { green: 0, amber: 0, red: 0 }
        for (const i of live) counts[i.confidence.triage] += 1
        return {
          order_id: o.order_id,
          created_at: o.created_at,
          source: o.source,
          item_count: live.length,
          counts,
          worst_triage: worstTriage(o.items),
          total_inr: o.total_inr,
        }
      })
      .sort(
        (a, b) =>
          TRIAGE_RANK[a.worst_triage] - TRIAGE_RANK[b.worst_triage] ||
          Date.parse(a.created_at) - Date.parse(b.created_at),
      )
  }

  async review(orderId: string, body: ReviewRequest): Promise<Order> {
    await this.io()
    this.sync()
    const order = clone(this.get(orderId))
    if (order.status !== 'pending_review') {
      throw new ApiRequestError(409, 'invalid_transition', `This order is already ${order.status.replace('_', ' ')}.`)
    }
    const reviewed_at = new Date(this.opts.now()).toISOString()
    const note = body.note?.trim() || null
    if (body.decision === 'reject') {
      if (!note) invalid('Add a note so the customer knows why.')
      return this.save({ ...order, status: 'rejected', pharmacist_note: note, reviewed_at })
    }
    const decisions = new Map<string, ItemDecision>()
    for (const d of body.items ?? []) decisions.set(d.item_id, d)
    for (const id of decisions.keys()) {
      if (!order.items.some((i) => i.item_id === id)) notFound(`Item ${id}`)
    }
    order.items = order.items.map((item) => {
      const d = decisions.get(item.item_id)
      if (!d || d.action === 'approve') {
        return { ...item, status: item.status === 'removed' ? 'removed' : 'approved' }
      }
      if (d.action === 'remove') return { ...item, status: 'removed' }
      const sku = d.sku_id ? (findSku(d.sku_id) ?? notFound(`SKU ${d.sku_id}`)) : item.sku
      if (!sku) invalid(`Pick a SKU for line ${item.parsed?.line_no ?? item.item_id}.`)
      const qty = d.quantity_packs ?? item.quantity_packs
      if (!Number.isInteger(qty) || qty < 1 || qty > 99) invalid('Quantity must be 1 to 99 packs.')
      const skuChanged = sku.sku_id !== item.sku?.sku_id
      return {
        ...item,
        sku,
        quantity_packs: qty,
        generic_alternative: skuChanged ? null : item.generic_alternative,
        savings_inr: skuChanged ? null : item.savings_inr,
        status: 'edited',
      }
    })
    if (order.items.every((i) => i.status === 'removed')) {
      invalid('Every line is removed. Reject the order instead.')
    }
    return this.save({ ...order, status: 'verified', pharmacist_note: note, reviewed_at })
  }

  async searchCatalog(q: string, limit = 10) {
    await this.io()
    return searchCatalog(q, limit)
  }

  // ---------- forecast ----------

  async forecastSummary() {
    await this.io()
    return forecastSummary()
  }

  async skuForecast(skuId: string, area: string) {
    await this.io()
    const summary = forecastSummary()
    if (!summary.skus.some((s) => s.sku_id === skuId) || !summary.areas.includes(area)) notFound('Forecast')
    return synthSeries(skuId, area)
  }

  async health() {
    await this.io()
    return { ok: true, mocks: true, database: false }
  }
}

export function localStore(key: string): KeyValueStore | undefined {
  try {
    const ls = globalThis.localStorage
    if (!ls) return undefined
    return {
      get: () => ls.getItem(key),
      set: (v) => ls.setItem(key, v),
      clear: () => ls.removeItem(key),
    }
  } catch {
    return undefined
  }
}
