import type { ErrorResponse } from '../contracts.gen'
import { ApiRequestError, PARSE_TIMEOUT_MS, timeoutError, type RioApi } from './types'

// Used when an error body isn't our JSON (e.g. a proxy's HTML 413 or 502 page).
const FALLBACK_MESSAGES: Record<number, string> = {
  413: 'That photo is over 5 MB. Try a smaller one.',
  429: 'Too many prescriptions this hour. Try again later, or try a sample.',
  502: 'We couldn’t read that prescription. Try a clearer photo, or try a sample.',
  503: 'Rio is restarting. Try again in a minute.',
  504: 'Reading the prescription took too long. Try again, or try a sample.',
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
      let message = FALLBACK_MESSAGES[res.status] ?? `Request failed (${res.status}).`
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
      form.append('image', image, 'prescription.jpg')
      return request('/api/orders/prescription', {
        method: 'POST',
        body: form,
        signal: AbortSignal.timeout(PARSE_TIMEOUT_MS),
      })
    },
    createSampleOrder: (id) =>
      request(`/api/orders/sample/${enc(id)}`, { ...json('POST'), signal: AbortSignal.timeout(PARSE_TIMEOUT_MS) }),
    createTextOrder: (text) => request('/api/orders/text', json('POST', { text })),
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
