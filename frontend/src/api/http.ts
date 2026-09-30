import type { ErrorResponse } from '../contracts.gen'
import { ApiRequestError, type RioApi } from './types'

export function createHttpApi(baseUrl: string): RioApi {
  const base = baseUrl.replace(/\/+$/, '')

  async function request<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetch(base + path, init)
    if (!res.ok) {
      let code = 'http_' + res.status
      let message = `Request failed (${res.status}).`
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
      return request('/api/orders/prescription', { method: 'POST', body: form })
    },
    createSampleOrder: (id) => request(`/api/orders/sample/${enc(id)}`, json('POST')),
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
