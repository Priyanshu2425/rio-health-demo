import { useEffect, useRef, useState } from 'react'
import { api, errorMessage, type QueueItem } from '../api'
import { Money, TriageBadge, timeAgo } from '../components/bits'
import { usePoll } from '../lib/usePoll'
import { OrderView } from './OrderView'
import './pharmacist.css'

export function Console({ focusOrderId }: { focusOrderId?: string | null }) {
  const [queue, setQueue] = useState<QueueItem[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [fresh, setFresh] = useState<Set<string>>(new Set())
  const seen = useRef<Set<string> | null>(null)
  const [, tick] = useState(0)

  const refresh = async () => {
    try {
      const q = await api.getQueue()
      setError(null)
      setQueue(q)
      // Flag orders that arrived since the last poll, so a new one is easy to spot.
      if (seen.current) {
        const arrived = q.filter((x) => !seen.current!.has(x.order_id)).map((x) => x.order_id)
        if (arrived.length) setFresh((f) => new Set([...f, ...arrived]))
      }
      seen.current = new Set(q.map((x) => x.order_id))
      setSelected((cur) => cur ?? q[0]?.order_id ?? null)
    } catch (e) {
      setError(errorMessage(e))
    }
  }
  usePoll(refresh, 2000)

  // Keep "2 min ago" labels moving.
  useEffect(() => {
    const id = setInterval(() => tick((n) => n + 1), 30_000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    if (focusOrderId) setSelected(focusOrderId)
  }, [focusOrderId])

  const next = () => {
    const other = queue?.find((q) => q.order_id !== selected)
    setSelected(other?.order_id ?? null)
  }

  return (
    <section className="console" aria-label="Pharmacist console">
      <nav className="queue" aria-label="Orders waiting for review">
        <div className="queue-head">
          <h2>Queue</h2>
          <span className="muted num">{queue ? `${queue.length} waiting` : '…'}</span>
        </div>
        {error && <p className="queue-error">{error}</p>}
        {queue?.length === 0 && (
          <p className="queue-empty">No prescriptions waiting. New ones show up here within 2 seconds.</p>
        )}
        <ol className="queue-list">
          {queue?.map((q) => (
            <li key={q.order_id}>
              <button
                className={`qrow qrow-${q.worst_triage}${selected === q.order_id ? ' is-on' : ''}${fresh.has(q.order_id) ? ' is-new' : ''}`}
                aria-current={selected === q.order_id ? 'true' : undefined}
                onClick={() => {
                  setSelected(q.order_id)
                  setFresh((f) => {
                    const n = new Set(f)
                    n.delete(q.order_id)
                    return n
                  })
                }}
              >
                <TriageBadge triage={q.worst_triage} label={false} />
                <span className="qrow-main">
                  <span className="qrow-title">
                    {q.item_count} line{q.item_count === 1 ? '' : 's'}
                    {fresh.has(q.order_id) && <span className="qrow-new">New</span>}
                  </span>
                  <span className="qrow-counts num">
                    {(['red', 'amber', 'green'] as const).map((t) =>
                      q.counts[t] ? (
                        <span key={t} className={`qc qc-${t}`}>
                          {q.counts[t]} {t === 'red' ? 'fix' : t === 'amber' ? 'check' : 'clear'}
                        </span>
                      ) : null,
                    )}
                  </span>
                </span>
                <span className="qrow-side">
                  <Money value={q.total_inr} />
                  <span className="muted">{timeAgo(q.created_at)}</span>
                </span>
              </button>
            </li>
          ))}
        </ol>
      </nav>
      <div className="detail">
        {selected ? (
          <OrderView key={selected} orderId={selected} onReviewed={refresh} onNext={next} />
        ) : (
          <div className="ov-empty">
            <p>
              <strong>All caught up.</strong> Orders appear here as soon as a customer sends a prescription.
            </p>
          </div>
        )}
      </div>
    </section>
  )
}
