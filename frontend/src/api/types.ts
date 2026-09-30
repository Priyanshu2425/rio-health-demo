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

/** Parser trouble (502/504) and rate limits (429): the UI offers a sample instead. */
export function isParserTrouble(err: unknown): boolean {
  return err instanceof ApiRequestError && [429, 502, 504].includes(err.status)
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiRequestError) return err.message
  if (err instanceof TypeError) return 'Can’t reach Rio right now. Check your connection and try again.'
  return 'Something went wrong. Try again.'
}
