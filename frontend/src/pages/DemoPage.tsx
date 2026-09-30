import { useState } from 'react'
import { Chat } from '../chat/Chat'
import { Console } from '../pharmacist/Console'
import './demo.css'

type Tab = 'customer' | 'pharmacist'

/** `/`: the customer's phone on the left, the pharmacist's console on the right, one shared order state. */
export function DemoPage() {
  const [focus, setFocus] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('customer')
  const [unseen, setUnseen] = useState(false)

  return (
    <div className={`demo demo-tab-${tab}`}>
      <div className="demo-tabs" role="tablist" aria-label="Demo side">
        <button role="tab" aria-selected={tab === 'customer'} onClick={() => setTab('customer')}>
          Customer
        </button>
        <button
          role="tab"
          aria-selected={tab === 'pharmacist'}
          onClick={() => {
            setTab('pharmacist')
            setUnseen(false)
          }}
        >
          Pharmacist
          {unseen && <span className="demo-dot" aria-label="new order" />}
        </button>
      </div>

      <div className="demo-phone-col">
        <p className="demo-caption">Customer, on their phone</p>
        <div className="phone">
          <div className="phone-notch" aria-hidden="true" />
          <div className="phone-screen">
            <Chat
              onOrderCreated={(id) => {
                setFocus(id)
                setUnseen(true)
              }}
            />
          </div>
        </div>
      </div>

      <div className="demo-console-col">
        <p className="demo-caption">Pharmacist, at the counter</p>
        <div className="demo-console console-host">
          <Console focusOrderId={focus} />
        </div>
      </div>
    </div>
  )
}
