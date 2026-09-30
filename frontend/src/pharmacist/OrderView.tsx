import { useEffect, useState } from 'react'
import { api, errorMessage, type Order } from '../api'
import { Dots, Money, Stamp, TriageBadge, timeAgo } from '../components/bits'
import { RxImage } from './RxImage'
import { LineCard } from './LineCard'
import { TRIAGE_ORDER, blockers, decidedTotal, groupByTriage, toReviewRequest, type Decisions } from './review'

const GROUP_TITLE = { red: 'Fix before approving', amber: 'Check these', green: 'Read cleanly' } as const

export function OrderView({ orderId, onReviewed, onNext }: { orderId: string; onReviewed: () => void; onNext?: () => void }) {
  const [order, setOrder] = useState<Order | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [decisions, setDecisions] = useState<Decisions>({})
  const [editing, setEditing] = useState<string | null>(null)
  const [rejecting, setRejecting] = useState(false)
  const [note, setNote] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  useEffect(() => {
    // The console keys this component by order id, so state starts fresh for each order.
    let alive = true
    api
      .getOrder(orderId)
      .then((o) => alive && setOrder(o))
      .catch((e) => alive && setLoadError(errorMessage(e)))
    return () => {
      alive = false
    }
  }, [orderId])

  if (loadError) return <div className="ov-empty">{loadError}</div>
  if (!order) {
    return (
      <div className="ov-empty">
        <Dots label="Loading order" />
      </div>
    )
  }

  const items = order.items.filter((i) => i.status !== 'removed' || order.status !== 'pending_review')
  const groups = groupByTriage(items)
  const open = order.status === 'pending_review'
  const blocking = blockers(items, decisions)
  const total = open ? decidedTotal(items, decisions) : order.total_inr
  const decidedCount = Object.keys(decisions).length
  const rx = order.parsed_rx

  const decide = (id: string, d: Decisions[string] | undefined) =>
    setDecisions((prev) => {
      const next = { ...prev }
      if (d) next[id] = d
      else delete next[id]
      return next
    })

  async function submit(kind: 'approve' | 'reject') {
    setSubmitting(true)
    setSubmitError(null)
    try {
      const body =
        kind === 'approve' ? toReviewRequest(decisions, note) : { decision: 'reject' as const, note: note.trim() }
      const o = await api.review(orderId, body)
      setOrder(o)
      setRejecting(false)
      onReviewed()
    } catch (e) {
      setSubmitError(errorMessage(e))
    } finally {
      setSubmitting(false)
    }
  }

  const greensOpen = groups.green.filter((i) => !decisions[i.item_id])

  return (
    <div className="ov">
      <header className="ov-head">
        <div className="ov-title">
          <h2>{rx?.patient_name ?? 'Customer'}</h2>
          <span className="muted">
            {order.source === 'sample' ? 'Sample prescription' : 'Prescription photo'} · {timeAgo(order.created_at)} ·{' '}
            <span className="num">{order.order_id}</span>
          </span>
        </div>
        {rx && (
          <dl className="ov-meta">
            <div>
              <dt>Doctor</dt>
              <dd>{rx.doctor_name ?? '—'}</dd>
            </div>
            <div>
              <dt>Clinic</dt>
              <dd>{rx.clinic_name ?? '—'}</dd>
            </div>
            <div>
              <dt>Rx date</dt>
              <dd className="num">{rx.rx_date ?? '—'}</dd>
            </div>
            <div>
              <dt>Read in</dt>
              <dd className="num">{(rx.latency_ms / 1000).toFixed(1)} s</dd>
            </div>
          </dl>
        )}
      </header>

      <div className="ov-body">
        {order.has_image && <RxImage src={api.orderImageUrl(order.order_id)} />}

        <div className="ov-lines">
          {!open && (
            <div className={`ov-result ov-result-${order.status}`}>
              {order.status === 'rejected' ? (
                <Stamp rejected>Rejected</Stamp>
              ) : (
                <Stamp>Verified by pharmacist</Stamp>
              )}
              <p>
                {order.status === 'rejected'
                  ? 'The customer has been told why.'
                  : 'The customer’s chat now shows the verified cart.'}
              </p>
              {onNext && (
                <button className="btn btn-sm" onClick={onNext}>
                  Next in queue
                </button>
              )}
            </div>
          )}

          {TRIAGE_ORDER.map((t) =>
            groups[t].length === 0 ? null : (
              <section key={t} className={`group group-${t}`}>
                <header className="group-head">
                  <TriageBadge triage={t} label={false} />
                  <h3>
                    {GROUP_TITLE[t]} <span className="muted num">{groups[t].length}</span>
                  </h3>
                  {t === 'green' && open && greensOpen.length > 0 && (
                    <button
                      className="btn btn-sm act-approve"
                      onClick={() =>
                        setDecisions((prev) => {
                          const next = { ...prev }
                          for (const i of greensOpen) next[i.item_id] = { action: 'approve' }
                          return next
                        })
                      }
                    >
                      ✓ Approve all green
                    </button>
                  )}
                </header>
                {groups[t].map((item) => (
                  <LineCard
                    key={item.item_id}
                    item={item}
                    readOnly={!open}
                    decision={open ? decisions[item.item_id] : undefined}
                    editing={editing === item.item_id}
                    disabled={!open || submitting}
                    onDecide={(d) => decide(item.item_id, d)}
                    onEdit={(on) => setEditing(on ? item.item_id : null)}
                  />
                ))}
              </section>
            ),
          )}
        </div>
      </div>

      {open && (
        <footer className="ov-foot">
          {rejecting ? (
            <div className="reject">
              <label className="reject-label" htmlFor="reject-note">
                Tell the customer why
              </label>
              <textarea
                id="reject-note"
                className="field"
                rows={2}
                autoFocus
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="e.g. The prescription is older than 6 months. Please send a current one."
              />
              <div className="ov-foot-actions">
                <button className="btn btn-quiet" onClick={() => setRejecting(false)} disabled={submitting}>
                  Cancel
                </button>
                <button className="btn btn-danger" disabled={!note.trim() || submitting} onClick={() => submit('reject')}>
                  Send rejection
                </button>
              </div>
            </div>
          ) : (
            <>
              <div className="ov-foot-sum">
                <span className="muted">
                  {decidedCount} of {items.length} lines decided
                  {blocking.length > 0 && (
                    <>
                      {' · '}
                      <span className="blocker">
                        Decide {blocking.length === 1 ? 'the red line' : `${blocking.length} red lines`} first
                      </span>
                    </>
                  )}
                </span>
                <span className="ov-total">
                  Total <Money value={total} />
                </span>
              </div>
              <div className="ov-foot-actions">
                <button className="btn btn-danger" onClick={() => setRejecting(true)} disabled={submitting}>
                  Reject with note
                </button>
                <button
                  className="btn btn-primary"
                  disabled={blocking.length > 0 || submitting || editing !== null}
                  onClick={() => submit('approve')}
                >
                  {submitting ? 'Approving…' : 'Approve order'}
                </button>
              </div>
            </>
          )}
          {submitError && <p className="ov-error">{submitError}</p>}
        </footer>
      )}
    </div>
  )
}
