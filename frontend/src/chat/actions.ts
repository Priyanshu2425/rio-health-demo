// Chat side effects that don't need React, kept here so they can be tested against the mock API.
import { isConflict, type Order, type RioApi } from '../api'

/** Swaps are allowed before review and on confirmed OTC carts (contracts/API.md). */
export function canSwap(order: Order): boolean {
  return order.status === 'pending_review' || order.status === 'confirmed_otc'
}

export interface Outcome {
  /** The order as it is now. */
  order: Order
  /** False when the server said the order had moved on (409) and we reloaded it instead. */
  applied: boolean
}

/** Run an order action; on invalid_transition, reload the order and return its current state. */
async function orReload(api: RioApi, orderId: string, action: () => Promise<Order>): Promise<Outcome> {
  try {
    return { order: await action(), applied: true }
  } catch (err) {
    if (!isConflict(err)) throw err
    return { order: await api.getOrder(orderId), applied: false }
  }
}

export function placeOrder(api: RioApi, orderId: string): Promise<Outcome> {
  return orReload(api, orderId, () => api.place(orderId))
}

export function swapItem(api: RioApi, orderId: string, itemId: string, useGeneric: boolean): Promise<Outcome> {
  return orReload(api, orderId, () => api.swap(orderId, { item_id: itemId, use_generic: useGeneric }))
}

/**
 * One polling tick over every order waiting on the pharmacist. Each order has its own
 * try/catch, so one failed request doesn't skip the others. Returns the orders whose status changed.
 */
export async function pollWaiting(
  api: Pick<RioApi, 'getOrder'>,
  waiting: Order[],
  onError?: (orderId: string, err: unknown) => void,
): Promise<{ before: Order; after: Order }[]> {
  const results = await Promise.all(
    waiting.map(async (before) => {
      try {
        const after = await api.getOrder(before.order_id)
        return after.status === before.status ? null : { before, after }
      } catch (err) {
        onError?.(before.order_id, err)
        return null
      }
    }),
  )
  return results.filter((r): r is { before: Order; after: Order } => r !== null)
}
