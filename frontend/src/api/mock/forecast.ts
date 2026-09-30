// Forecast data for the mock API. The summary comes from contracts/fixtures; the hourly
// series are synthesised per SKU × area (hour-of-day curve, noise, and one injected spike on
// Dolo 650 in Area A) because the fixture ships a single flat series.
import type { ForecastPoint, ForecastSummary, ReorderSuggestion, SkuForecast } from '../../contracts.gen'
import summaryFixture from '../../../../contracts/fixtures/forecast_summary.json'
import skuFixture from '../../../../contracts/fixtures/sku_forecast.json'

const SUMMARY = summaryFixture as unknown as ForecastSummary
const FIXTURE_SERIES = skuFixture as unknown as SkuForecast

const HOURS = FIXTURE_SERIES.points.length // 120
const NOW_INDEX = FIXTURE_SERIES.points.filter((p) => p.actual != null).length - 1
const START = Date.parse(FIXTURE_SERIES.points[0].ts)

const BASE: Record<string, number> = { sku_dolo_650: 6, sku_electral_21g: 3.2, sku_pan_40: 2.1 }
const AREA: Record<string, number> = { 'Area A': 1, 'Area B': 0.72, 'Area C': 0.5 }

function rng(seed: number) {
  let s = seed >>> 0
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0
    return s / 2 ** 32
  }
}

function hash(str: string): number {
  let h = 2166136261
  for (let i = 0; i < str.length; i++) h = Math.imul(h ^ str.charCodeAt(i), 16777619)
  return h >>> 0
}

// Demand by hour of day (IST): quiet overnight, a late-morning and an evening peak.
function hourShape(hour: number): number {
  const morning = Math.exp(-((hour - 11) ** 2) / 8)
  const evening = Math.exp(-((hour - 19.5) ** 2) / 6) * 1.25
  return 0.18 + morning + evening
}

const toIST = (ms: number) => {
  const d = new Date(ms + 5.5 * 3600_000)
  const iso = d.toISOString().slice(0, 19)
  return { iso: `${iso}+05:30`, hour: d.getUTCHours() }
}

export function isSpikeSeries(skuId: string, area: string) {
  return skuId === 'sku_dolo_650' && area === 'Area A'
}

export function synthSeries(skuId: string, area: string): SkuForecast {
  const base = (BASE[skuId] ?? 2.5) * (AREA[area] ?? 0.6)
  const rand = rng(hash(skuId + area))
  const spike = isSpikeSeries(skuId, area)
  const spikeStart = NOW_INDEX - 20
  const points: ForecastPoint[] = []
  let errModel = 0
  let errNaive = 0
  let n = 0
  const actuals: number[] = []
  for (let i = 0; i < HOURS; i++) {
    const { iso, hour } = toIST(START + i * 3600_000)
    const expected = base * hourShape(hour)
    const lift = spike && i >= spikeStart ? 1 + Math.min(1.6, (i - spikeStart) * 0.12) : 1
    // After "now" the model has picked up the higher 7-day level on the spiking series.
    const level = spike && i > NOW_INDEX ? 1.9 : spike && i >= spikeStart ? 1 + (i - spikeStart) * 0.035 : 1
    const forecast = Math.round(expected * level * 10) / 10
    let actual: number | null = null
    if (i <= NOW_INDEX) {
      actual = Math.max(0, Math.round(expected * lift * (0.82 + rand() * 0.36) * 10) / 10)
      actuals.push(actual)
      if (actual > 0.5) {
        errModel += Math.abs(forecast - actual) / actual
        const lastWeek = expected * (0.75 + rand() * 0.5)
        errNaive += Math.abs(lastWeek - actual) / actual
        n++
      }
    }
    points.push({ ts: iso, forecast, actual })
  }
  return {
    sku_id: skuId,
    area,
    brand_name: SUMMARY.skus.find((s) => s.sku_id === skuId)?.brand_name ?? skuId,
    model_mape: Math.round((errModel / Math.max(n, 1)) * 100) / 100,
    naive_mape: Math.round((errNaive / Math.max(n, 1)) * 100) / 100,
    points,
  }
}

function reorderFor(skuId: string, area: string): ReorderSuggestion {
  const series = synthSeries(skuId, area)
  const leadTime = 12 // hours
  const future = series.points.slice(NOW_INDEX + 1, NOW_INDEX + 1 + leadTime)
  const demand = Math.round(future.reduce((a, p) => a + p.forecast, 0) * 10) / 10
  const rand = rng(hash('stock' + skuId + area))
  const onHand = isSpikeSeries(skuId, area) ? 12 : Math.round(demand * (1.3 + rand() * 1.6))
  let cum = 0
  let hoursToStockout: number | null = null
  for (let i = 0; i < future.length; i++) {
    cum += future[i].forecast
    if (cum >= onHand) {
      hoursToStockout = Math.round((i + (onHand - (cum - future[i].forecast)) / future[i].forecast) * 10) / 10
      break
    }
  }
  const risk = hoursToStockout != null
  return {
    sku_id: skuId,
    brand_name: series.brand_name,
    area,
    on_hand: onHand,
    forecast_over_lead_time: demand,
    reorder_qty: risk ? Math.ceil((demand * 2 - onHand) / 6) * 6 : 0,
    stockout_risk: risk,
    hours_to_stockout: hoursToStockout,
  }
}

export function forecastSummary(): ForecastSummary {
  const reorders: ReorderSuggestion[] = []
  for (const s of SUMMARY.skus) for (const a of SUMMARY.areas) reorders.push(reorderFor(s.sku_id, a))
  reorders.sort(
    (x, y) =>
      Number(y.stockout_risk) - Number(x.stockout_risk) ||
      (x.hours_to_stockout ?? Infinity) - (y.hours_to_stockout ?? Infinity) ||
      y.forecast_over_lead_time - x.forecast_over_lead_time,
  )
  return { ...SUMMARY, reorders }
}

export const FORECAST_NOW_INDEX = NOW_INDEX
