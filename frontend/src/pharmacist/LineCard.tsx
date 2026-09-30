import type { CartItem, ParsedLine, SKU } from '../api'
import { Money, TriageBadge } from '../components/bits'
import type { Decision } from './review'
import { SkuPicker } from './SkuPicker'

const FIELDS: { key: keyof ParsedLine; label: string; illegible: ParsedLine['illegible_fields'][number] }[] = [
  { key: 'drug', label: 'Drug', illegible: 'drug' },
  { key: 'strength', label: 'Strength', illegible: 'strength' },
  { key: 'form', label: 'Form', illegible: 'form' },
  { key: 'frequency', label: 'Dose', illegible: 'frequency' },
  { key: 'duration_days', label: 'Days', illegible: 'duration' },
  { key: 'quantity', label: 'Qty written', illegible: 'quantity' },
]

function SkuSummary({ sku, struck }: { sku: SKU; struck?: boolean }) {
  const body = (
    <>
      <span className="sku-brand">{sku.brand_name}</span>
      <span className="sku-sub">
        {sku.composition_key} · {sku.pack_label} · {sku.manufacturer}
      </span>
    </>
  )
  return <div className={`sku${struck ? ' sku-struck' : ''}`}>{struck ? <s>{body}</s> : body}</div>
}

export function LineCard({
  item,
  decision,
  editing,
  disabled,
  readOnly,
  onDecide,
  onEdit,
}: {
  item: CartItem
  decision: Decision | undefined
  editing: boolean
  disabled: boolean
  readOnly?: boolean
  onDecide: (d: Decision | undefined) => void
  onEdit: (open: boolean) => void
}) {
  const p = item.parsed
  const c = item.confidence
  const removed = decision?.action === 'remove'
  const edited = decision?.action === 'edit' ? decision : null
  const sku = edited ? edited.sku : item.sku
  const qty = edited ? edited.quantity_packs : item.quantity_packs
  const fromStatus = item.status === 'pending' ? 'open' : item.status
  const state = removed ? 'removed' : edited ? 'edited' : decision?.action === 'approve' ? 'approved' : fromStatus

  return (
    <article className={`line line-${c.triage} line-${state}`} aria-label={`Line ${p?.line_no ?? ''}`}>
      <header className="line-head">
        <TriageBadge triage={c.triage} />
        <span className="line-no">Line {p?.line_no ?? '–'}</span>
        <span className="line-score num" title="Combined confidence: match, completeness and legibility">
          {Math.round(c.score * 100)}%
        </span>
        <span className="line-state">
          {state === 'approved' && <span className="tag tag-ok">✓ Approved</span>}
          {state === 'edited' && <span className="tag tag-edit">✎ Edited</span>}
          {state === 'removed' && <span className="tag tag-removed">Removed</span>}
        </span>
      </header>

      <blockquote className="raw" title="The line as written on the prescription">
        {p?.raw_text ?? item.requested_text}
      </blockquote>

      {p && (
        <dl className="parsed">
          {FIELDS.map((f) => {
            const v = p[f.key]
            const bad = p.illegible_fields.includes(f.illegible)
            return (
              <div key={f.key} className={bad ? 'is-bad' : v == null ? 'is-empty' : undefined}>
                <dt>{f.label}</dt>
                <dd>
                  {v == null ? '—' : String(v)}
                  {bad && <span className="bad-mark"> unclear</span>}
                </dd>
              </div>
            )
          })}
        </dl>
      )}

      <div className="match">
        <div className="match-sku">
          {edited && item.sku && <SkuSummary sku={item.sku} struck />}
          {sku ? <SkuSummary sku={sku} /> : <div className="sku sku-none">No SKU matched. Pick one or remove the line.</div>}
        </div>
        <div className="match-price">
          {sku && (
            <>
              <span className="num">
                {qty} × <Money value={sku.mrp_inr} />
              </span>
              <strong>
                <Money value={removed ? 0 : sku.mrp_inr * qty} />
              </strong>
            </>
          )}
          {sku?.rx_only && <span className="pill pill-rx">Schedule {sku.schedule ?? 'H'}</span>}
        </div>
      </div>

      {c.reasons.length > 0 && (
        <ul className="reasons">
          {c.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}

      {readOnly ? null : editing ? (
        <SkuPicker
          item={item}
          current={{ sku, quantity_packs: qty }}
          onCancel={() => onEdit(false)}
          onSave={(s, n) => {
            onDecide({ action: 'edit', sku: s, quantity_packs: n })
            onEdit(false)
          }}
        />
      ) : (
        <div className="line-actions">
          {state === 'open' ? (
            <>
              <button
                className="btn btn-sm act-approve"
                disabled={disabled || !item.sku}
                title={item.sku ? undefined : 'Pick a SKU first'}
                onClick={() => onDecide({ action: 'approve' })}
              >
                ✓ Approve
              </button>
              <button className="btn btn-sm" disabled={disabled} onClick={() => onEdit(true)}>
                ✎ Edit
              </button>
              <button className="btn btn-sm btn-danger" disabled={disabled} onClick={() => onDecide({ action: 'remove' })}>
                Remove
              </button>
            </>
          ) : (
            <>
              {state === 'edited' && (
                <button className="btn btn-sm" disabled={disabled} onClick={() => onEdit(true)}>
                  ✎ Change again
                </button>
              )}
              <button className="btn btn-sm btn-quiet" disabled={disabled} onClick={() => onDecide(undefined)}>
                Undo
              </button>
            </>
          )}
        </div>
      )}
    </article>
  )
}
