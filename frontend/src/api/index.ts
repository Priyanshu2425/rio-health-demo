import { resolveApiBase } from './config'
import { createHttpApi } from './http'
import type { RioApi } from './types'

export * from './types'

// Compared literally so Vite can constant-fold it: with VITE_MOCKS unset the mock branch,
// its fixtures and the dynamic import below are dropped from the production bundle.
export const USE_MOCKS = import.meta.env.VITE_MOCKS === '1' || import.meta.env.VITE_MOCKS === 'true'

interface MockHandle extends RioApi {
  reset(): void
}

function query(name: string): string | null {
  try {
    return new URLSearchParams(window.location.search).get(name)
  } catch {
    return null
  }
}

async function loadMock(): Promise<MockHandle> {
  const { MockServer, localStore } = await import('./mock/server')
  // Rehearsal knobs on mocks: ?fail=<error code> fails the next upload; ?latency=<ms> sets parse time.
  const latency = Number(query('latency'))
  return new MockServer({
    store: localStore('rio.mock.v1'),
    failMode: () => query('fail'),
    parseLatencyMs: Number.isFinite(latency) && latency > 0 ? latency : undefined,
  })
}

const mock: MockHandle | null = USE_MOCKS ? await loadMock() : null

const { baseUrl, error } = resolveApiBase({
  VITE_API_BASE_URL: import.meta.env.VITE_API_BASE_URL,
  DEV: import.meta.env.DEV,
  mocks: USE_MOCKS,
})

/** Set when a production build has no API address; App.tsx shows it as a banner. */
export const API_CONFIG_ERROR: string | null = error
if (API_CONFIG_ERROR) console.error(`[rio] ${API_CONFIG_ERROR}`)

export const api: RioApi = mock ?? createHttpApi(baseUrl)

/** Mock only: wipe orders back to the seeded queue, for a clean Loom take. */
export function resetMockState() {
  mock?.reset()
}
