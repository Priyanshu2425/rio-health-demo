// Shapes seen on the live API in Wave 2 part B.
import { describe, expect, it } from 'vitest'
import type { ForecastSummary, ReorderSuggestion } from '../contracts.gen'
import { sameScore } from '../pharmacist/review'
import { pickDefault } from './forecastDefault'

const row = (sku_id: string, area: string, demand: number, risk: boolean): ReorderSuggestion => ({
  sku_id,
  brand_name: sku_id,
  area,
  on_hand: 10,
  forecast_over_lead_time: demand,
  reorder_qty: risk ? 20 : 0,
  stockout_risk: risk,
  hours_to_stockout: risk ? 4 : null,
})

const summary = (reorders: ReorderSuggestion[]): ForecastSummary => ({
  areas: ['Area A', 'Area B'],
  backtest: { horizon_days: 14, model_mape: 0.2288, naive_mape: 0.2851 },
  generated_at: '2026-09-30T19:54:00+05:30',
  reorders,
  skus: [{ sku_id: 'sku_x', brand_name: 'X' }],
})

describe('forecast default selection', () => {
  it('opens on the at-risk series with the most demand, not the soonest stockout', () => {
    // The backend sorts by hours to stockout; the spike SKUs have the biggest demand.
    const s = summary([
      row('sku_telma_40', 'Area C', 17.06, true),
      row('sku_crocin_650', 'Area B', 131.2, true),
      row('sku_dolo_650', 'Area B', 108.63, true),
      row('sku_pan_40', 'Area A', 300, false),
    ])
    expect(pickDefault(s)).toEqual({ skuId: 'sku_crocin_650', area: 'Area B' })
  })

  it('falls back to the first row, then the first SKU and area', () => {
    expect(pickDefault(summary([row('sku_a', 'Area B', 5, false)]))).toEqual({ skuId: 'sku_a', area: 'Area B' })
    expect(pickDefault(summary([]))).toEqual({ skuId: 'sku_x', area: 'Area A' })
  })
})

describe('catalog search ties', () => {
  it('treats scores that round to the same percent as tied', () => {
    expect(sameScore(0.8635, 0.8635)).toBe(true)
    expect(sameScore(0.8635, 0.8641)).toBe(true)
    expect(sameScore(0.87, 0.65)).toBe(false)
  })
})
