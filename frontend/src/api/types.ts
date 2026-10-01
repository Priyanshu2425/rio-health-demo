import type {
  Confidence,
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

export type Triage = Confidence['triage']
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
  /** The email wall: record the visitor's email. 204 on success. */
  registerVisitor(email: string): Promise<void>
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

/** Error codes from contracts/API.md, plus the client's own timeout. */
export type ErrorCode =
  | 'unsupported_image'
  | 'not_found'
  | 'no_forecast'
  | 'invalid_transition'
  | 'image_too_large'
  | 'invalid_request'
  | 'rate_limited'
  | 'parser_failed'
  | 'parser_timeout'
  | 'client_timeout'

/**
 * A non-JSON error (e.g. a proxy's HTML page) has no code; http.ts marks it `http_<status>`.
 * Only for those do we fall back to the HTTP status.
 */
export function isUncoded(err: ApiRequestError): boolean {
  return err.code.startsWith('http_')
}

function hasCode(err: unknown, codes: ErrorCode[], statuses: number[]): err is ApiRequestError {
  if (!(err instanceof ApiRequestError)) return false
  if ((codes as string[]).includes(err.code)) return true
  return isUncoded(err) && statuses.includes(err.status)
}

/** Parser trouble, rate limits and unreadable files: the chat offers a sample instead. */
export function isParserTrouble(err: unknown): boolean {
  return hasCode(
    err,
    ['rate_limited', 'parser_failed', 'parser_timeout', 'client_timeout', 'unsupported_image', 'image_too_large'],
    [400, 413, 429, 502, 504],
  )
}

/** invalid_transition: the order changed under us (e.g. the pharmacist reviewed it). Reload it. */
export function isConflict(err: unknown): boolean {
  return hasCode(err, ['invalid_transition'], [409])
}

/** Minutes to wait, read from a rate_limited message such as "Try again in 23 minutes." */
export function retryMinutes(message: string): number | null {
  const m = /(\d+)\s*(?:min|minute)/i.exec(message)
  if (m) return parseInt(m[1], 10)
  const s = /(\d+)\s*(?:s|sec|second)s?\b/i.exec(message)
  if (s) return Math.max(1, Math.ceil(parseInt(s[1], 10) / 60))
  return null
}

/** Our own copy, used only when the server sent no message (non-JSON error bodies). */
export const FALLBACK_BY_CODE: Record<ErrorCode, string> = {
  unsupported_image: 'That file isn’t a photo we can read. Send a JPEG, PNG or WebP picture of the prescription.',
  image_too_large: 'That photo is over 5 MB. Try a smaller one.',
  rate_limited: 'You’ve sent a lot of prescriptions this hour. Try again later, or try a sample.',
  parser_failed: 'We couldn’t read that prescription. Try a clearer photo, or try a sample.',
  parser_timeout: 'Reading the prescription took too long. Try again, or try a sample.',
  client_timeout: 'Reading this prescription is taking too long. Try again in a minute, or try a sample.',
  invalid_transition: 'This order has changed. Here is the latest.',
  invalid_request: 'Something in that request wasn’t right. Try again.',
  not_found: 'We couldn’t find that.',
  no_forecast: 'No forecast yet. It appears after the first nightly run.',
}

export const FALLBACK_BY_STATUS: Record<number, ErrorCode> = {
  400: 'unsupported_image',
  404: 'not_found',
  409: 'invalid_transition',
  413: 'image_too_large',
  422: 'invalid_request',
  429: 'rate_limited',
  502: 'parser_failed',
  504: 'parser_timeout',
}

/** What to tell the user: the server's `error.message` when there is one, else our fallback copy. */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiRequestError) {
    if (err.code === 'rate_limited') {
      // Agreed with the backend: the only number in a rate_limited message is the wait in minutes.
      const mins = retryMinutes(err.message)
      if (mins != null) {
        return `You’ve sent a lot of prescriptions this hour. Try again in ${mins} minute${mins === 1 ? '' : 's'}, or try a sample.`
      }
    }
    if (err.message) return err.message
    const code = (err.code in FALLBACK_BY_CODE ? err.code : FALLBACK_BY_STATUS[err.status]) as ErrorCode | undefined
    return (code && FALLBACK_BY_CODE[code]) || `Request failed (${err.status}).`
  }
  if (err instanceof TypeError) return 'Can’t reach Rio right now. Check your connection and try again.'
  return 'Something went wrong. Try again.'
}
