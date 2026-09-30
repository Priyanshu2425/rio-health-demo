import type { ErrorResponse } from '../contracts.gen'
import {
  ApiRequestError,
  FALLBACK_BY_CODE,
  FALLBACK_BY_STATUS,
  PARSE_TIMEOUT_MS,
  timeoutError,
  type RioApi,
} from './types'

/** Copy for a status when the body isn't our JSON (e.g. a proxy's HTML 413 or 502 page). */
function statusMessage(status: number): string {
  if (status === 503) return 'Rio is restarting. Try again in a minute.'
  const code = FALLBACK_BY_STATUS[status]
  return code ? FALLBACK_BY_CODE[code] : `Request failed (${status}).`
}


export function createHttpApi(baseUrl: string): RioApi {
  const base = baseUrl.replace(/\/+$/, '')

  async function request<T>(path: string, init?: RequestInit): Promise<T> {
    let res: Response
    try {
      res = await fetch(base + path, init)
    } catch (err) {
      if (err instanceof DOMException && (err.name === 'TimeoutError' || err.name === 'AbortError')) throw timeoutError()
      throw err
    }
    if (!res.ok) {
      let code = 'http_' + res.status
      let message = statusMessage(res.status)
      try {
        const body = (await res.json()) as ErrorResponse
        if (body?.error?.message) {
          code = body.error.code
          message = body.error.message
        }
      } catch {
        /* not JSON: keep the generic message */
      }
      throw new ApiRequestError(res.status, code, message)
    }
    return (await res.json()) as T
  }

  const json = (method: string, body?: unknown): RequestInit => ({
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const enc = encodeURIComponent

  return {
    isMock: false,
    createPrescriptionOrder(image) {
      const form = new FormData()
      // A resized upload is a JPEG Blob; if resizing failed it's the original File, so keep its name.
      form.append('image', image, image instanceof File ? image.name : 'prescription.jpg')
      return request('/api/orders/prescription', {
        method: 'POST',
        body: form,
        signal: AbortSignal.timeout(PARSE_TIMEOUT_MS),
      })
    },
    createSampleOrder: (id) =>
      request(`/api/orders/sample/${enc(id)}`, { ...json('POST'), signal: AbortSignal.timeout(PARSE_TIMEOUT_MS) }),
    createTextOrder: (text) =>
      request('/api/orders/text', { ...json('POST', { text }), signal: AbortSignal.timeout(PARSE_TIMEOUT_MS) }),
    getOrder: (id) => request(`/api/orders/${enc(id)}`),
    orderImageUrl: (id) => `${base}/api/orders/${enc(id)}/image`,
    swap: (id, body) => request(`/api/orders/${enc(id)}/swap`, json('POST', body)),
    place: (id) => request(`/api/orders/${enc(id)}/place`, json('POST')),
    listSamples: () => request('/api/samples'),
    sampleImageUrl: (id) => `${base}/api/samples/${enc(id)}/image`,
    getQueue: () => request('/api/queue'),
    review: (id, body) => request(`/api/queue/${enc(id)}/review`, json('POST', body)),
    searchCatalog: (q, limit = 10) =>
      request(`/api/catalog/search?q=${enc(q)}&limit=${Math.min(limit, 20)}`),
    forecastSummary: () => request('/api/forecast/summary'),
    skuForecast: (sku, area) => request(`/api/forecast/sku/${enc(sku)}?area=${enc(area)}`),
    health: () => request('/api/health'),
  }
}
