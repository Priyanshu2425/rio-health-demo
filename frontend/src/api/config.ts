export interface ApiEnv {
  VITE_API_BASE_URL?: string
  DEV: boolean
  mocks: boolean
}

/**
 * localhost is a dev-only default. A production build without VITE_API_BASE_URL must not
 * quietly call the visitor's own machine, so it reports a config error instead (shown in App.tsx).
 */
export function resolveApiBase(env: ApiEnv): { baseUrl: string; error: string | null } {
  const baseUrl = env.VITE_API_BASE_URL?.trim() || (env.DEV ? 'http://localhost:8000' : '')
  const error =
    !env.mocks && !baseUrl
      ? 'This build has no API address. Set VITE_API_BASE_URL (e.g. https://rio-api.buildspacelabs.com) and rebuild.'
      : null
  return { baseUrl, error }
}
