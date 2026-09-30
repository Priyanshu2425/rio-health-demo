import { describe, expect, it } from 'vitest'
import { PENDING_FIXTURE } from '../api/mock/orders'
import { findSku } from '../api/mock/catalog'
import { fitWithin } from '../lib/resizeImage'
import { blockers, decidedTotal, groupByTriage, toReviewRequest, type Decisions } from './review'

const items = PENDING_FIXTURE.items

describe('pharmacist review helpers', () => {
  it('groups lines red, amber, green', () => {
    const g = groupByTriage(items)
    expect(g.red.map((i) => i.item_id)).toEqual(['itm_3'])
    expect(g.amber.map((i) => i.item_id)).toEqual(['itm_2'])
    expect(g.green.map((i) => i.item_id)).toEqual(['itm_1'])
  })

  it('blocks approval until the red line is decided', () => {
    expect(blockers(items, {}).map((i) => i.item_id)).toEqual(['itm_3'])
    expect(blockers(items, { itm_3: { action: 'approve' } })).toEqual([])
  })

  it('recomputes the total from decisions', () => {
    const crocin = findSku('sku_crocin_650')!
    const d: Decisions = { itm_2: { action: 'remove' }, itm_3: { action: 'edit', sku: crocin, quantity_packs: 2 } }
    expect(decidedTotal(items, {})).toBe(412.1)
    expect(decidedTotal(items, d)).toBe(223.5 + 69)
  })

  it('builds the ReviewRequest body', () => {
    const crocin = findSku('sku_crocin_650')!
    const body = toReviewRequest({ itm_1: { action: 'approve' }, itm_3: { action: 'edit', sku: crocin, quantity_packs: 2 } }, '  ')
    expect(body).toEqual({
      decision: 'approve',
      note: null,
      items: [
        { item_id: 'itm_1', action: 'approve' },
        { item_id: 'itm_3', action: 'edit', sku_id: 'sku_crocin_650', quantity_packs: 2 },
      ],
    })
  })
})

describe('upload resize target', () => {
  it('caps the longest side at 1600 px and keeps the aspect ratio', () => {
    expect(fitWithin(4032, 3024)).toEqual({ width: 1600, height: 1200 })
    expect(fitWithin(3000, 4000)).toEqual({ width: 1200, height: 1600 })
  })
  it('never upscales', () => {
    expect(fitWithin(800, 600)).toEqual({ width: 800, height: 600 })
  })
})
