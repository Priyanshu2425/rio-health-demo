import type { Triage } from '../api'
import { formatINR } from '../lib/money'
import { TRIAGE_META } from '../lib/triage'


/** Colour-blind-safe triage badge: shape + glyph + word, never colour alone. */
export function TriageBadge({ triage, label, bare }: { triage: Triage; label?: string | false; bare?: boolean }) {
  const meta = TRIAGE_META[triage]
  const text = label === false ? null : (label ?? meta.label)
  return (
    <span className={`triage triage-${triage}${bare ? ' triage-bare' : ''}`} title={`${triage} line`}>
      <span className="triage-icon" aria-hidden="true">
        {meta.icon}
      </span>
      {text ?? <span className="sr-only">{meta.label}</span>}
    </span>
  )
}

export function Money({ value, className }: { value: number | null | undefined; className?: string }) {
  return <span className={`money${className ? ' ' + className : ''}`}>{formatINR(value)}</span>
}

export function Dots({ label }: { label?: string }) {
  return (
    <span className="dots" role="status" aria-label={label ?? 'Loading'}>
      <span />
      <span />
      <span />
    </span>
  )
}

export function Stamp({ rejected, children }: { rejected?: boolean; children: React.ReactNode }) {
  return (
    <span className={`stamp${rejected ? ' stamp-rejected' : ''}`}>
      <span className="stamp-check" aria-hidden="true">
        {rejected ? '✕' : '✓'}
      </span>
      {children}
    </span>
  )
}

export function timeAgo(iso: string, now = Date.now()): string {
  const s = Math.max(0, Math.round((now - Date.parse(iso)) / 1000))
  if (s < 45) return 'just now'
  const m = Math.round(s / 60)
  if (m < 60) return `${m} min ago`
  const h = Math.round(m / 60)
  if (h < 24) return `${h} h ago`
  return `${Math.round(h / 24)} d ago`
}
