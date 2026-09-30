import { createHttpApi } from './http'
import { MockServer, localStore } from './mock/server'
import type { RioApi } from './types'

export * from './types'

export const USE_MOCKS = import.meta.env.VITE_MOCKS === '1' || import.meta.env.VITE_MOCKS === 'true'

// Add ?fail=parser_failed | parser_timeout | rate_limited to the URL to rehearse the failure path on mocks.
function failMode(): string | null {
  try {
    return new URLSearchParams(window.location.search).get('fail')
  } catch {
    return null
  }
}

const mock = USE_MOCKS ? new MockServer({ store: localStore('rio.mock.v1'), failMode }) : null

export const api: RioApi =
  mock ?? createHttpApi(import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000')

/** Mock only: wipe orders back to the seeded queue, for a clean Loom take. */
export function resetMockState() {
  mock?.reset()
}
