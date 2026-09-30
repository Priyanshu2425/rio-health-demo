import { Suspense, lazy } from 'react'
import { API_CONFIG_ERROR, USE_MOCKS, resetMockState } from './api'
import { navigate, useRoute, type Route } from './lib/router'
import { ChatPage } from './pages/ChatPage'
import { DemoPage } from './pages/DemoPage'
import { PharmacistPage } from './pages/PharmacistPage'
import './shell.css'

// Recharts is only needed on the forecast tab; keep it out of the demo's first load.
const ForecastPage = lazy(() => import('./pages/ForecastPage').then((m) => ({ default: m.ForecastPage })))

const NAV: { to: Route; label: string }[] = [
  { to: '/', label: 'Demo' },
  { to: '/chat', label: 'Customer chat' },
  { to: '/pharmacist', label: 'Pharmacist' },
  { to: '/forecast', label: 'Forecast' },
]

export default function App() {
  const route = useRoute()
  return (
    <div className={`shell shell-${route === '/' ? 'demo' : route.slice(1)}`}>
      <header className="appbar">
        <a
          className="wordmark"
          href="/"
          onClick={(e) => {
            e.preventDefault()
            navigate('/')
          }}
        >
          <svg viewBox="0 0 32 32" width="26" height="26" aria-hidden="true">
            <rect width="32" height="32" rx="8" fill="var(--accent)" />
            <path d="M13 7h6v6h6v6h-6v6h-6v-6H7v-6h6z" fill="#fff" />
          </svg>
          <span>Rio</span>
          <span className="wordmark-sub">prescription desk</span>
        </a>
        <nav className="appnav" aria-label="Views">
          {NAV.map((n) => (
            <a
              key={n.to}
              href={n.to}
              aria-current={route === n.to ? 'page' : undefined}
              onClick={(e) => {
                e.preventDefault()
                navigate(n.to)
              }}
            >
              {n.label}
            </a>
          ))}
        </nav>
        {USE_MOCKS && (
          <div className="mockflag">
            <span className="pill" title="Running on the in-browser mock API">
              Mock data
            </span>
            <button
              className="btn btn-sm btn-quiet"
              onClick={() => {
                resetMockState()
                window.location.reload()
              }}
            >
              Reset demo
            </button>
          </div>
        )}
      </header>
      {API_CONFIG_ERROR && (
        <div className="config-error" role="alert">
          <strong>Not connected.</strong> {API_CONFIG_ERROR}
        </div>
      )}
      <main className="stage">
        {route === '/' && <DemoPage />}
        {route === '/chat' && <ChatPage />}
        {route === '/pharmacist' && <PharmacistPage />}
        {route === '/forecast' && (
          <Suspense fallback={null}>
            <ForecastPage />
          </Suspense>
        )}
      </main>
    </div>
  )
}
