import { useEffect, useState } from 'react'

export type Route = '/' | '/chat' | '/pharmacist' | '/forecast'
const ROUTES: Route[] = ['/', '/chat', '/pharmacist', '/forecast']

function current(): Route {
  const p = window.location.pathname.replace(/\/+$/, '') || '/'
  return (ROUTES as string[]).includes(p) ? (p as Route) : '/'
}

export function navigate(to: Route) {
  if (to === current()) return
  window.history.pushState(null, '', to + window.location.search)
  window.dispatchEvent(new PopStateEvent('popstate'))
}

export function useRoute(): Route {
  const [route, setRoute] = useState(current)
  useEffect(() => {
    const on = () => setRoute(current())
    window.addEventListener('popstate', on)
    return () => window.removeEventListener('popstate', on)
  }, [])
  return route
}
