import type { ForecastSummary } from '../contracts.gen'

export interface Selection {
  skuId: string
  area: string
}

/** Open on the stockout risk with the most demand: that's where a demand spike shows. */
export function pickDefault(summary: ForecastSummary): Selection {
  const risky = summary.reorders
    .filter((r) => r.stockout_risk)
    .reduce<ForecastSummary['reorders'][number] | null>(
      (best, r) => (!best || r.forecast_over_lead_time > best.forecast_over_lead_time ? r : best),
      null,
    )
  if (risky) return { skuId: risky.sku_id, area: risky.area }
  const first = summary.reorders[0]
  if (first) return { skuId: first.sku_id, area: first.area }
  return { skuId: summary.skus[0]?.sku_id ?? '', area: summary.areas[0] ?? '' }
}

