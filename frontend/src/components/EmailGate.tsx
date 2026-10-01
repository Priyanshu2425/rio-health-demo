import { useState, type FormEvent, type ReactNode } from 'react'
import { api, ApiRequestError } from '../api'

const STORAGE_KEY = 'rio.visitor.email'

/** Same shape the API accepts: something@something.tld, no spaces. Never verified. */
export function isPlausibleEmail(value: string): boolean {
  return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(value.trim())
}

function savedEmail(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

function saveEmail(email: string) {
  try {
    localStorage.setItem(STORAGE_KEY, email)
  } catch {
    /* private mode: the wall shows again next visit, which is fine */
  }
}

/** Asks for an email once per browser before showing the demo. */
export function EmailGate({ children }: { children: ReactNode }) {
  const [done, setDone] = useState(() => savedEmail() !== null)
  const [email, setEmail] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (done) return <>{children}</>

  async function submit(e: FormEvent) {
    e.preventDefault()
    const value = email.trim()
    if (!isPlausibleEmail(value)) {
      setError('Please enter a valid email address, like name@example.com.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await api.registerVisitor(value)
      saveEmail(value)
      setDone(true)
    } catch (err) {
      setError(err instanceof ApiRequestError ? err.message : 'We couldn’t reach Rio. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="gate">
      <form className="gate-card" onSubmit={submit} noValidate>
        <svg viewBox="0 0 32 32" width="40" height="40" aria-hidden="true">
          <rect width="32" height="32" rx="8" fill="var(--accent)" />
          <path d="M13 7h6v6h6v6h-6v6h-6v-6H7v-6h6z" fill="#fff" />
        </svg>
        <h1>Rio prescription desk</h1>
        <p>
          A photo of a prescription becomes a pharmacist-verified cart. Enter your email to try
          the demo.
        </p>
        <label htmlFor="gate-email">Email</label>
        <input
          id="gate-email"
          className="field"
          type="email"
          inputMode="email"
          autoComplete="email"
          placeholder="name@example.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? 'gate-error' : undefined}
          autoFocus
        />
        {error && (
          <p id="gate-error" className="gate-error" role="alert">
            {error}
          </p>
        )}
        <button className="btn btn-primary" type="submit" disabled={busy}>
          {busy ? 'Opening…' : 'Open the demo'}
        </button>
      </form>
    </div>
  )
}
