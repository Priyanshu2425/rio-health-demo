import { useCallback, useEffect, useRef, useState } from 'react'
import { api, errorMessage, isParserTrouble, type CartItem, type Order, type Sample } from '../api'
import { Dots, Money, Stamp } from '../components/bits'
import { resizeImage } from '../lib/resizeImage'
import { usePoll } from '../lib/usePoll'
import { CartLines, CartTotal, DiffLines } from './CartLines'
import './chat.css'

type Quick = 'upload' | 'sample' | 'type'

type Msg =
  | { id: number; kind: 'rio'; text: string; quick?: Quick[] }
  | { id: number; kind: 'user-text'; text: string }
  | { id: number; kind: 'user-photo'; src: string; caption?: string }
  | { id: number; kind: 'typing'; text: string }
  | { id: number; kind: 'samples' }
  | { id: number; kind: 'cart'; orderId: string }
  | { id: number; kind: 'verified'; orderId: string }
  | { id: number; kind: 'rejected'; orderId: string }
  | { id: number; kind: 'placed'; orderId: string }
  | { id: number; kind: 'needs-rx'; orderId: string }
  | { id: number; kind: 'error'; text: string; offerSample: boolean }

const QUICK_LABEL: Record<Quick, string> = {
  upload: '📷 Upload prescription',
  sample: 'Try a sample',
  type: 'Type medicines',
}

let seq = 0
const mid = () => ++seq

const GREETING: Msg = {
  id: 0,
  kind: 'rio',
  text: 'Hi, I’m Rio. Send a photo of your prescription and I’ll build your cart. A licensed pharmacist checks every prescription order before it ships.',
  quick: ['upload', 'sample', 'type'],
}

export interface ChatProps {
  /** Demo mode: tell the pharmacist pane which order just arrived. */
  onOrderCreated?: (orderId: string) => void
}

export function Chat({ onOrderCreated }: ChatProps) {
  const [msgs, setMsgs] = useState<Msg[]>([GREETING])
  const [orders, setOrders] = useState<Record<string, Order>>({})
  // What the customer saw before review, so pharmacist edits can be shown as a diff.
  const [before, setBefore] = useState<Record<string, Order>>({})
  const [busy, setBusy] = useState(false)
  const [samples, setSamples] = useState<Sample[] | null>(null)
  const [text, setText] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  const push = useCallback((...m: Msg[]) => setMsgs((prev) => [...prev, ...m]), [])
  const drop = useCallback((id: number) => setMsgs((prev) => prev.filter((m) => m.id !== id)), [])

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  }, [msgs, orders])

  const track = useCallback(
    (order: Order) => {
      setOrders((o) => ({ ...o, [order.order_id]: order }))
      if (order.status === 'pending_review') setBefore((b) => ({ ...b, [order.order_id]: order }))
    },
    [],
  )

  // Poll every order still waiting on the pharmacist.
  const waiting = Object.values(orders).filter((o) => o.status === 'pending_review')
  usePoll(
    async () => {
      for (const o of waiting) {
        const fresh = await api.getOrder(o.order_id)
        if (fresh.status === o.status) continue
        setOrders((prev) => ({ ...prev, [fresh.order_id]: fresh }))
        if (fresh.status === 'verified') push({ id: mid(), kind: 'verified', orderId: fresh.order_id })
        else if (fresh.status === 'rejected') push({ id: mid(), kind: 'rejected', orderId: fresh.order_id })
      }
    },
    2000,
    waiting.length > 0,
  )

  async function run(label: string, create: () => Promise<Order>) {
    setBusy(true)
    const typingId = mid()
    push({ id: typingId, kind: 'typing', text: label })
    try {
      const order = await create()
      drop(typingId)
      track(order)
      if (order.status === 'needs_prescription') push({ id: mid(), kind: 'needs-rx', orderId: order.order_id })
      else push({ id: mid(), kind: 'cart', orderId: order.order_id })
      if (order.status === 'pending_review') onOrderCreated?.(order.order_id)
    } catch (err) {
      drop(typingId)
      push({ id: mid(), kind: 'error', text: errorMessage(err), offerSample: isParserTrouble(err) })
    } finally {
      setBusy(false)
    }
  }

  async function onFile(file: File | undefined) {
    if (!file) return
    const blob = await resizeImage(file)
    push({ id: mid(), kind: 'user-photo', src: URL.createObjectURL(blob) })
    await run('Reading your prescription…', () => api.createPrescriptionOrder(blob))
  }

  async function showSamples() {
    push({ id: mid(), kind: 'user-text', text: 'Try a sample' }, { id: mid(), kind: 'samples' })
    if (!samples) {
      try {
        setSamples(await api.listSamples())
      } catch (err) {
        push({ id: mid(), kind: 'error', text: errorMessage(err), offerSample: false })
      }
    }
  }

  async function pickSample(s: Sample) {
    setMsgs((prev) => prev.filter((m) => m.kind !== 'samples'))
    push({ id: mid(), kind: 'user-photo', src: api.sampleImageUrl(s.sample_id), caption: s.label })
    await run('Reading your prescription…', () => api.createSampleOrder(s.sample_id))
  }

  async function sendText() {
    const t = text.trim()
    if (!t || busy) return
    setText('')
    push({ id: mid(), kind: 'user-text', text: t })
    await run('Checking our shelves…', () => api.createTextOrder(t))
  }

  async function swap(orderId: string, item: CartItem, useGeneric: boolean) {
    setBusy(true)
    try {
      const o = await api.swap(orderId, { item_id: item.item_id, use_generic: useGeneric })
      track(o)
    } catch (err) {
      push({ id: mid(), kind: 'error', text: errorMessage(err), offerSample: false })
    } finally {
      setBusy(false)
    }
  }

  async function place(orderId: string) {
    setBusy(true)
    try {
      const o = await api.place(orderId)
      setOrders((prev) => ({ ...prev, [o.order_id]: o }))
      push({ id: mid(), kind: 'user-text', text: 'Place order' }, { id: mid(), kind: 'placed', orderId })
    } catch (err) {
      push({ id: mid(), kind: 'error', text: errorMessage(err), offerSample: false })
    } finally {
      setBusy(false)
    }
  }

  function quick(q: Quick) {
    if (q === 'upload') fileRef.current?.click()
    else if (q === 'sample') void showSamples()
    else inputRef.current?.focus()
  }

  const lastRioIdx = msgs.map((m) => m.kind).lastIndexOf('rio')

  return (
    <section className="chat" aria-label="Customer chat with Rio">
      <header className="chat-head">
        <span className="chat-avatar" aria-hidden="true">
          <svg viewBox="0 0 32 32" width="22" height="22">
            <path d="M13 7h6v6h6v6h-6v6h-6v-6H7v-6h6z" fill="#fff" />
          </svg>
        </span>
        <div>
          <div className="chat-title">Rio Pharmacy</div>
          <div className="chat-sub">Pharmacist-checked orders · usually replies in minutes</div>
        </div>
      </header>

      <div className="chat-scroll" ref={scrollRef}>
        <div className="chat-day">Today</div>
        {msgs.map((m, idx) => {
          switch (m.kind) {
            case 'rio':
              return (
                <div key={m.id} className="row row-in">
                  <div className="bubble bubble-in">
                    <p>{m.text}</p>
                  </div>
                  {m.quick && idx === lastRioIdx && !busy && (
                    <div className="quick">
                      {m.quick.map((q) => (
                        <button key={q} className="quick-btn" onClick={() => quick(q)}>
                          {QUICK_LABEL[q]}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )
            case 'user-text':
              return (
                <div key={m.id} className="row row-out">
                  <div className="bubble bubble-out">
                    <p>{m.text}</p>
                  </div>
                </div>
              )
            case 'user-photo':
              return (
                <div key={m.id} className="row row-out">
                  <figure className="bubble bubble-out bubble-photo">
                    <img src={m.src} alt="Prescription photo you sent" />
                    {m.caption && <figcaption>{m.caption}</figcaption>}
                  </figure>
                </div>
              )
            case 'typing':
              return (
                <div key={m.id} className="row row-in">
                  <div className="bubble bubble-in bubble-typing">
                    <Dots label={m.text} />
                    <span>{m.text}</span>
                  </div>
                </div>
              )
            case 'samples':
              return (
                <div key={m.id} className="row row-in">
                  <div className="bubble bubble-in">
                    <p>Pick a prescription to try. These are real formats we see every day.</p>
                    {!samples ? (
                      <Dots />
                    ) : (
                      <div className="samples">
                        {samples.map((s) => (
                          <button key={s.sample_id} className="sample" disabled={busy} onClick={() => pickSample(s)}>
                            <img src={api.sampleImageUrl(s.sample_id)} alt="" />
                            <span>{s.label}</span>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              )
            case 'cart': {
              const order = orders[m.orderId]
              if (!order) return null
              const pending = order.status === 'pending_review'
              // Before review the card is live (swaps update it); afterwards it freezes at what was sent for review.
              const shown = pending ? order : (before[m.orderId] ?? order)
              const otc = order.source === 'text'
              const live = shown.items.filter((i) => i.status !== 'removed')
              return (
                <div key={m.id} className="row row-in">
                  <div className="bubble bubble-in bubble-card">
                    <div className="card-head">
                      <span className="card-title">Your cart</span>
                      <span className="muted">
                        {live.length} medicine{live.length === 1 ? '' : 's'}
                      </span>
                    </div>
                    <CartLines
                      order={shown}
                      swappable={pending}
                      busy={busy}
                      onSwap={(item, g) => swap(order.order_id, item, g)}
                    />
                    <CartTotal order={shown} />
                    {pending && (
                      <div className="card-status card-status-wait">
                        <span className="pulse" aria-hidden="true" />A pharmacist is verifying your order.
                      </div>
                    )}
                    {!pending && !otc && order.status !== 'rejected' && (
                      <div className="card-status card-status-done">Checked by a pharmacist. See below.</div>
                    )}
                    {otc && order.status === 'confirmed_otc' && (
                      <>
                        <div className="card-status">These are over-the-counter, so no prescription is needed.</div>
                        <button className="btn btn-primary card-cta" disabled={busy} onClick={() => place(order.order_id)}>
                          Place order · <Money value={order.total_inr} />
                        </button>
                      </>
                    )}
                    {otc && order.items.some((i) => !i.sku) && (
                      <div className="card-status muted">
                        Not found: {order.items.filter((i) => !i.sku).map((i) => i.requested_text).join(', ')}
                      </div>
                    )}
                  </div>
                </div>
              )
            }
            case 'verified': {
              const order = orders[m.orderId]
              if (!order) return null
              return (
                <div key={m.id} className="row row-in">
                  <div className="bubble bubble-in bubble-card bubble-verified">
                    <Stamp>Verified by pharmacist</Stamp>
                    <DiffLines before={before[m.orderId]} after={order} />
                    <CartTotal order={order} before={before[m.orderId]} />
                    {order.pharmacist_note && (
                      <blockquote className="note">
                        <span className="muted">Pharmacist’s note</span>
                        {order.pharmacist_note}
                      </blockquote>
                    )}
                    {order.status === 'verified' && (
                      <button className="btn btn-primary card-cta" disabled={busy} onClick={() => place(order.order_id)}>
                        Place order · <Money value={order.total_inr} />
                      </button>
                    )}
                  </div>
                </div>
              )
            }
            case 'rejected': {
              const order = orders[m.orderId]
              return (
                <div key={m.id} className="row row-in">
                  <div className="bubble bubble-in bubble-card">
                    <Stamp rejected>Not approved</Stamp>
                    <p>The pharmacist couldn’t approve this prescription.</p>
                    {order?.pharmacist_note && (
                      <blockquote className="note">
                        <span className="muted">Pharmacist’s note</span>
                        {order.pharmacist_note}
                      </blockquote>
                    )}
                    <div className="quick quick-inline">
                      <button className="quick-btn" onClick={() => quick('upload')} disabled={busy}>
                        {QUICK_LABEL.upload}
                      </button>
                    </div>
                  </div>
                </div>
              )
            }
            case 'placed':
              return (
                <div key={m.id} className="row row-in">
                  <div className="bubble bubble-in">
                    <p>
                      <strong>Order placed.</strong> Payment and delivery tracking would follow here; this demo stops at
                      the order.
                    </p>
                  </div>
                </div>
              )
            case 'needs-rx': {
              const order = orders[m.orderId]
              const rx = order?.items.filter((i) => i.sku?.rx_only) ?? []
              return (
                <div key={m.id} className="row row-in">
                  <div className="bubble bubble-in">
                    <p>
                      <strong>{rx.map((i) => i.sku!.brand_name).join(', ')}</strong>{' '}
                      {rx.length === 1 ? 'needs' : 'need'} a prescription. Upload one?
                    </p>
                  </div>
                  {!busy && (
                    <div className="quick">
                      <button className="quick-btn" onClick={() => quick('upload')}>
                        {QUICK_LABEL.upload}
                      </button>
                      <button className="quick-btn" onClick={() => quick('sample')}>
                        {QUICK_LABEL.sample}
                      </button>
                    </div>
                  )}
                </div>
              )
            }
            case 'error':
              return (
                <div key={m.id} className="row row-in">
                  <div className="bubble bubble-in bubble-error">
                    <p>{m.text}</p>
                  </div>
                  {m.offerSample && !busy && (
                    <div className="quick">
                      <button className="quick-btn" onClick={() => quick('sample')}>
                        {QUICK_LABEL.sample}
                      </button>
                    </div>
                  )}
                </div>
              )
          }
        })}
      </div>

      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault()
          void sendText()
        }}
      >
        <button
          type="button"
          className="composer-cam"
          aria-label="Send a prescription photo"
          disabled={busy}
          onClick={() => fileRef.current?.click()}
        >
          <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
            <path
              d="M9 4h6l1.5 2H20a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h3.5z"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinejoin="round"
            />
            <circle cx="12" cy="12.5" r="3.5" fill="none" stroke="currentColor" strokeWidth="1.8" />
          </svg>
        </button>
        <input
          ref={inputRef}
          className="composer-input"
          placeholder="Type medicines, e.g. Dolo 650, ORS"
          value={text}
          onChange={(e) => setText(e.target.value)}
          aria-label="Message"
        />
        <button type="submit" className="composer-send" disabled={busy || !text.trim()} aria-label="Send">
          <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
            <path d="M4 12l16-8-6 16-2.5-6.5z" fill="currentColor" />
          </svg>
        </button>
        <input
          ref={fileRef}
          type="file"
          accept="image/jpeg,image/png,image/webp,image/*"
          hidden
          onChange={(e) => {
            void onFile(e.target.files?.[0])
            e.target.value = ''
          }}
        />
      </form>
    </section>
  )
}
