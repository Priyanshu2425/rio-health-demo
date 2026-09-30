import type { CartItem, Order } from '../api'
import { Money } from '../components/bits'

function packs(n: number) {
  return `${n} pack${n === 1 ? '' : 's'}`
}

export function isSwapped(item: CartItem): boolean {
  return !!(item.generic_alternative && item.sku && item.generic_alternative.sku_id === item.sku.sku_id)
}

function lineName(item: CartItem): string {
  return item.sku?.brand_name ?? item.parsed?.drug ?? item.requested_text ?? item.parsed?.raw_text ?? 'Unreadable line'
}

interface LineProps {
  item: CartItem
  swappable?: boolean
  busy?: boolean
  onSwap?: (item: CartItem, useGeneric: boolean) => void
}

function Line({ item, swappable, busy, onSwap }: LineProps) {
  const swapped = isSwapped(item)
  return (
    <li className="cl-line">
      <div className="cl-main">
        <span className="cl-name">{lineName(item)}</span>
        {item.sku ? <Money value={item.line_total_inr} className="cl-price" /> : <span className="cl-price muted">—</span>}
      </div>
      <div className="cl-meta">
        {item.sku ? (
          <>
            {item.sku.pack_label} · {packs(item.quantity_packs)}
            {item.sku.rx_only && <span className="pill pill-rx">Rx</span>}
          </>
        ) : (
          <span>We couldn’t match this one. The pharmacist will pick it.</span>
        )}
      </div>
      {swappable && item.generic_alternative && item.savings_inr != null && item.savings_inr > 0 && onSwap && (
        <div className="cl-swap">
          {swapped ? (
            <>
              <span className="swap-done">
                ✓ Switched to generic, saving <Money value={item.savings_inr} />
              </span>
              <button className="linkbtn" disabled={busy} onClick={() => onSwap(item, false)}>
                Undo
              </button>
            </>
          ) : (
            <button
              className="swap-chip"
              disabled={busy}
              onClick={() => onSwap(item, true)}
              title={`Same composition: ${item.generic_alternative.brand_name} by ${item.generic_alternative.manufacturer}`}
            >
              Save <Money value={item.savings_inr} /> — switch to generic
            </button>
          )}
        </div>
      )}
    </li>
  )
}

export function CartLines({
  order,
  swappable,
  busy,
  onSwap,
}: {
  order: Order
  swappable?: boolean
  busy?: boolean
  onSwap?: (item: CartItem, useGeneric: boolean) => void
}) {
  const live = order.items.filter((i) => i.status !== 'removed')
  return (
    <ul className="cl">
      {live.map((item) => (
        <Line key={item.item_id} item={item} swappable={swappable} busy={busy} onSwap={onSwap} />
      ))}
    </ul>
  )
}

/** The verified cart, with the pharmacist's changes shown against what the customer first saw. */
export function DiffLines({ before, after }: { before: Order | undefined; after: Order }) {
  return (
    <ul className="cl">
      {after.items.map((item) => {
        const old = before?.items.find((i) => i.item_id === item.item_id)
        if (item.status === 'removed') {
          return (
            <li key={item.item_id} className="cl-line cl-removed">
              <div className="cl-main">
                <s className="cl-name">{lineName(old ?? item)}</s>
                <s className="money cl-price">
                  <Money value={(old ?? item).line_total_inr} />
                </s>
              </div>
              <div className="cl-meta cl-note">Removed by the pharmacist</div>
            </li>
          )
        }
        const skuChanged = !!old && old.sku?.sku_id !== item.sku?.sku_id
        const qtyChanged = !!old && old.quantity_packs !== item.quantity_packs
        const edited = item.status === 'edited' && (skuChanged || qtyChanged)
        return (
          <li key={item.item_id} className={`cl-line${edited ? ' cl-edited' : ''}`}>
            {edited && skuChanged && old && (
              <div className="cl-main cl-old">
                <s className="cl-name">{lineName(old)}</s>
                <s>
                  <Money value={old.line_total_inr} className="cl-price" />
                </s>
              </div>
            )}
            <div className="cl-main">
              <span className="cl-name">{lineName(item)}</span>
              <Money value={item.line_total_inr} className="cl-price" />
            </div>
            <div className="cl-meta">
              {item.sku?.pack_label} ·{' '}
              {qtyChanged && old ? (
                <>
                  <s>{packs(old.quantity_packs)}</s> {packs(item.quantity_packs)}
                </>
              ) : (
                packs(item.quantity_packs)
              )}
              {item.sku?.rx_only && <span className="pill pill-rx">Rx</span>}
            </div>
            {edited && <div className="cl-meta cl-note">Changed by the pharmacist</div>}
            {item.status === 'edited' && !edited && <div className="cl-meta cl-note">Confirmed by the pharmacist</div>}
          </li>
        )
      })}
    </ul>
  )
}

export function CartTotal({ order, before }: { order: Order; before?: Order }) {
  const changed = before && Math.abs(before.total_inr - order.total_inr) > 0.004
  return (
    <div className="cl-total">
      <span>Total</span>
      <span>
        {changed && (
          <s className="muted cl-total-old">
            <Money value={before!.total_inr} />
          </s>
        )}
        <Money value={order.total_inr} />
      </span>
    </div>
  )
}
