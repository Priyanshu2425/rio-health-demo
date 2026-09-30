import { useEffect, useState } from 'react'
import { api, errorMessage, type CartItem, type MatchCandidate, type SKU } from '../api'
import { Dots, Money } from '../components/bits'
import { sameScore } from './review'

function initialQuery(item: CartItem): string {
  const p = item.parsed
  if (p?.drug) return [p.drug, p.strength].filter(Boolean).join(' ')
  return item.sku?.brand_name ?? item.requested_text ?? ''
}

export function SkuPicker({
  item,
  current,
  onSave,
  onCancel,
}: {
  item: CartItem
  current: { sku: SKU | null; quantity_packs: number }
  onSave: (sku: SKU, qty: number) => void
  onCancel: () => void
}) {
  const [q, setQ] = useState(() => initialQuery(item))
  const [results, setResults] = useState<MatchCandidate[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [picked, setPicked] = useState<SKU | null>(current.sku)
  const [qty, setQty] = useState(current.quantity_packs)

  useEffect(() => {
    const term = q.trim()
    if (term.length < 2) {
      setResults([])
      return
    }
    let alive = true
    const t = setTimeout(() => {
      api
        .searchCatalog(term, 8)
        .then((r) => alive && (setResults(r), setError(null)))
        .catch((e) => alive && setError(errorMessage(e)))
    }, 180)
    return () => {
      alive = false
      clearTimeout(t)
    }
  }, [q])

  const qtyOk = Number.isInteger(qty) && qty >= 1 && qty <= 99

  return (
    <div className="picker" role="group" aria-label="Change SKU and quantity">
      <label className="picker-search">
        <span className="picker-label">Search the catalog</span>
        <input
          className="field"
          value={q}
          autoFocus
          onChange={(e) => setQ(e.target.value)}
          placeholder="Brand or salt, e.g. paracetamol 650"
        />
      </label>
      <div className="picker-results" aria-live="polite">
        {error && <p className="picker-empty">{error}</p>}
        {!error && results === null && <Dots label="Searching" />}
        {!error && results?.length === 0 && q.trim().length >= 2 && (
          <p className="picker-empty">No SKU matches “{q.trim()}”. Try the salt name.</p>
        )}
        {results && results.length > 1 && (
          <p className="picker-hint">Best match first; equal matches are ranked by how often they sell.</p>
        )}
        {results?.map((c, idx) => {
          const on = picked?.sku_id === c.sku.sku_id
          const tiedWithPrev = idx > 0 && sameScore(results[idx - 1].score, c.score)
          return (
            <button
              key={c.sku.sku_id}
              type="button"
              className={`picker-row${on ? ' is-on' : ''}`}
              aria-pressed={on}
              onClick={() => setPicked(c.sku)}
            >
              <span className="picker-radio" aria-hidden="true" />
              <span className="picker-main">
                <span className="picker-brand">
                  {c.sku.brand_name}
                  {c.sku.rx_only && <span className="pill pill-rx">Rx {c.sku.schedule}</span>}
                </span>
                <span className="picker-sub">
                  {c.sku.composition_key} · {c.sku.pack_label} · {c.sku.manufacturer}
                </span>
              </span>
              <span className="picker-side">
                <Money value={c.sku.mrp_inr} />
                <span className="picker-score num">
                  #{idx + 1} · {tiedWithPrev ? 'same match' : `${Math.round(c.score * 100)}% match`}
                </span>
              </span>
            </button>
          )
        })}
      </div>
      <div className="picker-foot">
        <label className="qty">
          <span className="picker-label">Packs</span>
          <span className="qty-box">
            <button type="button" aria-label="One fewer pack" onClick={() => setQty((n) => Math.max(1, n - 1))}>
              −
            </button>
            <input
              className="num"
              inputMode="numeric"
              value={Number.isNaN(qty) ? '' : qty}
              onChange={(e) => setQty(parseInt(e.target.value, 10))}
              aria-label="Packs"
            />
            <button type="button" aria-label="One more pack" onClick={() => setQty((n) => Math.min(99, (n || 0) + 1))}>
              +
            </button>
          </span>
        </label>
        {picked && qtyOk && (
          <span className="picker-preview">
            {picked.brand_name} × {qty} = <Money value={picked.mrp_inr * qty} />
          </span>
        )}
        <span className="picker-actions">
          <button type="button" className="btn btn-sm btn-quiet" onClick={onCancel}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-sm btn-primary"
            disabled={!picked || !qtyOk}
            onClick={() => picked && onSave(picked, qty)}
          >
            Use this SKU
          </button>
        </span>
      </div>
    </div>
  )
}
