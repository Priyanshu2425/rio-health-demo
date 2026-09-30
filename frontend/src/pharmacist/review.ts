// Pure helpers for the pharmacist's review screen, kept out of the components so they can be tested.
import type { CartItem, ItemDecision, ReviewRequest, SKU, Triage } from '../api'
import { roundINR, sumINR } from '../lib/money'

export type Decision =
  | { action: 'approve' }
  | { action: 'remove' }
  | { action: 'edit'; sku: SKU; quantity_packs: number }

export type Decisions = Record<string, Decision>

export const TRIAGE_ORDER: Triage[] = ['red', 'amber', 'green']

export function groupByTriage(items: CartItem[]): Record<Triage, CartItem[]> {
  const out: Record<Triage, CartItem[]> = { red: [], amber: [], green: [] }
  for (const i of items) out[i.confidence.triage].push(i)
  for (const t of TRIAGE_ORDER) out[t].sort((a, b) => (a.parsed?.line_no ?? 0) - (b.parsed?.line_no ?? 0))
  return out
}

/** Line total after the pharmacist's decision (0 when removed). */
export function decidedLineTotal(item: CartItem, d: Decision | undefined): number {
  if (d?.action === 'remove') return 0
  if (d?.action === 'edit') return roundINR(d.sku.mrp_inr * d.quantity_packs)
  return item.line_total_inr
}

export function decidedTotal(items: CartItem[], decisions: Decisions): number {
  return sumINR(items.filter((i) => i.status !== 'removed').map((i) => decidedLineTotal(i, decisions[i.item_id])))
}

/** Red lines need an explicit decision; a line with no SKU can only be edited or removed. */
export function blockers(items: CartItem[], decisions: Decisions): CartItem[] {
  return items.filter((i) => {
    if (i.status === 'removed') return false
    const d = decisions[i.item_id]
    if (!i.sku) return !d || d.action === 'approve'
    return i.confidence.triage === 'red' && !d
  })
}

export function toReviewRequest(decisions: Decisions, note: string): ReviewRequest {
  const items: ItemDecision[] = Object.entries(decisions).map(([item_id, d]) =>
    d.action === 'edit'
      ? { item_id, action: 'edit', sku_id: d.sku.sku_id, quantity_packs: d.quantity_packs }
      : { item_id, action: d.action },
  )
  return { decision: 'approve', items, note: note.trim() || null }
}

/** Scores that round to the same percent are a tie; the backend then ranks by popularity. */
export function sameScore(a: number, b: number): boolean {
  return Math.round(a * 100) === Math.round(b * 100)
}
