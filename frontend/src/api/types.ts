import type {
  ForecastSummary,
  MatchCandidate,
  Order,
  QueueItem,
  ReviewRequest,
  Sample,
  SkuForecast,
  SwapRequest,
} from '../contracts.gen'

export type * from '../contracts.gen'

export type Triage = 'green' | 'amber' | 'red'
export type OrderStatus = Order['status']

export interface Health {
  ok: boolean
  mocks: boolean
  database: boolean
}

/** One function per route in contracts/API.md. Both the HTTP client and the mock implement it. */
export interface RioApi {
  readonly isMock: boolean
  createPrescriptionOrder(image: Blob): Promise<Order>
  createSampleOrder(sampleId: string): Promise<Order>
  createTextOrder(text: string): Promise<Order>
  getOrder(orderId: string): Promise<Order>
  orderImageUrl(orderId: string): string
  swap(orderId: string, body: SwapRequest): Promise<Order>
  place(orderId: string): Promise<Order>
  listSamples(): Promise<Sample[]>
  sampleImageUrl(sampleId: string): string
  getQueue(): Promise<QueueItem[]>
  review(orderId: string, body: ReviewRequest): Promise<Order>
  searchCatalog(q: string, limit?: number): Promise<MatchCandidate[]>
  forecastSummary(): Promise<ForecastSummary>
  skuForecast(skuId: string, area: string): Promise<SkuForecast>
  health(): Promise<Health>
}

/** Every non-2xx response. `message` is ErrorResponse.error.message, safe to show a user. */
export class ApiRequestError extends Error {
  readonly status: number
  readonly code: string
  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'ApiRequestError'
    this.status = status
    this.code = code
  }
}

/** The backend gives a parse 75 s; the client waits a little longer before giving up. */
export const PARSE_TIMEOUT_MS = 90_000

export function timeoutError(): ApiRequestError {
  return new ApiRequestError(
    504,
    'client_timeout',
    'Reading this prescription is taking too long. Try again in a minute, or try a sample.',
  )
}

/** Reject with a 504-style error if `promise` hasn't settled within `ms`. */
export function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const t = setTimeout(() => reject(timeoutError()), ms)
    promise.then(
      (v) => (clearTimeout(t), resolve(v)),
      (e) => (clearTimeout(t), reject(e)),
    )
  })
}

/** Parser trouble (502/504), rate limits (429) and unreadable files (400, 413): offer a sample instead. */
export function isParserTrouble(err: unknown): boolean {
  return err instanceof ApiRequestError && [400, 413, 429, 502, 504].includes(err.status)
}

/** 409: someone else changed the order (e.g. the pharmacist reviewed it). Reload it. */
export function isConflict(err: unknown): boolean {
  return err instanceof ApiRequestError && err.status === 409
}

/** Minutes to wait, read from a 429 message such as "Try again in 23 minutes." */
export function retryMinutes(message: string): number | null {
  const m = /(\d+)\s*(?:min|minute)/i.exec(message)
  if (m) return parseInt(m[1], 10)
  const s = /(\d+)\s*(?:s|sec|second)s?\b/i.exec(message)
  if (s) return Math.max(1, Math.ceil(parseInt(s[1], 10) / 60))
  return null
}

/** What to tell the user. Always the server's `error.message`, with a clearer lead for a few codes. */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiRequestError) {
    if (err.code === 'unsupported_image' || err.status === 400) {
      return `That file isn’t a photo we can read. Send a JPEG, PNG or WebP picture of the prescription. (${err.message})`
    }
    if (err.status === 429) {
      const mins = retryMinutes(err.message)
      return mins != null
        ? `You’ve sent a lot of prescriptions this hour. Try again in ${mins} minute${mins === 1 ? '' : 's'}, or try a sample.`
        : err.message
    }
    return err.message
  }
  if (err instanceof TypeError) return 'Can’t reach Rio right now. Check your connection and try again.'
  return 'Something went wrong. Try again.'
}
