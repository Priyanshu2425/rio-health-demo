import type { Triage } from '../api/types'

/** One vocabulary for triage everywhere: glyph plus word, never colour alone. */
export const TRIAGE_META: Record<Triage, { icon: string; label: string }> = {
  green: { icon: '✓', label: 'Clear' },
  amber: { icon: '!', label: 'Check' },
  red: { icon: '✕', label: 'Fix' },
}
