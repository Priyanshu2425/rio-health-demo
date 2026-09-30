import { useEffect, useMemo, useState, useCallback } from 'react'
import {
  ResponsiveContainer,
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ReferenceArea,
} from 'recharts'
import type { ForecastSummary, SkuForecast, ForecastPoint } from '../contracts.gen'
import { api, errorMessage, ApiRequestError } from '../api'
import { TriageBadge, Dots } from '../components/bits'
import { pickDefault, type Selection } from '../lib/forecastDefault'
import './forecast.css'

const IST_FORMATTER = new Intl.DateTimeFormat('en-GB', {
  weekday: 'short',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
  timeZone: 'Asia/Kolkata',
})

function formatTick(ts: string): string {
  // en-GB gives "Tue, 18:00" style pieces; reassemble as "Tue 18:00".
  const parts = IST_FORMATTER.formatToParts(new Date(ts))
  const weekday = parts.find((p) => p.type === 'weekday')?.value ?? ''
  const hour = parts.find((p) => p.type === 'hour')?.value ?? ''
  const minute = parts.find((p) => p.type === 'minute')?.value ?? ''
  return `${weekday} ${hour}:${minute}`
}

function formatPct(fraction: number): string {
  return `${Math.round(fraction * 100)}%`
}

function formatHours(h: number | null): string {
  if (h == null) return '—'
  return `${Math.round(h * 10) / 10} h`
}

type ChartRow = { ts: string; actual: number | null; forecast: number | null }

export function ForecastPage() {
  const [summary, setSummary] = useState<ForecastSummary | null>(null)
  const [summaryError, setSummaryError] = useState<unknown>(null)
  const [summaryLoading, setSummaryLoading] = useState(true)
  const [noForecast, setNoForecast] = useState(false)

  const [selection, setSelection] = useState<Selection | null>(null)
  const [series, setSeries] = useState<SkuForecast | null>(null)
  const [seriesError, setSeriesError] = useState<unknown>(null)
  const [seriesLoading, setSeriesLoading] = useState(false)
  const [showAll, setShowAll] = useState(false)

  const loadSummary = useCallback(() => {
    setSummaryLoading(true)
    setSummaryError(null)
    setNoForecast(false)
    api
      .forecastSummary()
      .then((s) => {
        setSummary(s)
        setSelection((prev) => prev ?? pickDefault(s))
      })
      .catch((err: unknown) => {
        if (err instanceof ApiRequestError && err.status === 404 && err.code === 'no_forecast') {
          setNoForecast(true)
        } else {
          setSummaryError(err)
        }
      })
      .finally(() => setSummaryLoading(false))
  }, [])

  useEffect(() => {
    loadSummary()
  }, [loadSummary])

  useEffect(() => {
    if (!selection) return
    let cancelled = false
    setSeriesLoading(true)
    setSeriesError(null)
    api
      .skuForecast(selection.skuId, selection.area)
      .then((s) => {
        if (!cancelled) setSeries(s)
      })
      .catch((err: unknown) => {
        if (!cancelled) setSeriesError(err)
      })
      .finally(() => {
        if (!cancelled) setSeriesLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [selection])

  const chartData = useMemo<ChartRow[]>(() => {
    if (!series) return []
    return series.points.map((p: ForecastPoint) => ({
      ts: p.ts,
      actual: p.actual,
      forecast: p.forecast,
    }))
  }, [series])

  const nowTs = useMemo(() => {
    if (!series) return null
    let last: string | null = null
    for (const p of series.points) {
      if (p.actual != null) last = p.ts
    }
    return last
  }, [series])

  const endTs = series?.points[series.points.length - 1]?.ts ?? null

  if (summaryLoading) {
    return (
      <div className="forecast-page">
        <div className="forecast-panel forecast-status">
          <Dots label="Loading forecast" />
          <span>Loading forecast…</span>
        </div>
      </div>
    )
  }

  if (noForecast) {
    return (
      <div className="forecast-page">
        <div className="forecast-panel">
          <p>No forecast yet. It appears after the first nightly run.</p>
        </div>
      </div>
    )
  }

  if (summaryError || !summary) {
    return (
      <div className="forecast-page">
        <div className="forecast-panel forecast-error">
          <p>{errorMessage(summaryError)}</p>
          <button type="button" className="btn" onClick={loadSummary}>
            Retry
          </button>
        </div>
      </div>
    )
  }

  const riskCount = summary.reorders.filter((r) => r.stockout_risk).length
  const tableRows =
    showAll || riskCount === 0
      ? summary.reorders.slice(0, showAll ? undefined : 12)
      : summary.reorders.filter((r) => r.stockout_risk || (selection?.skuId === r.sku_id && selection.area === r.area))
  const backtest = summary.backtest
  const modelPct = formatPct(backtest.model_mape)
  const naivePct = formatPct(backtest.naive_mape)
  const maxMape = Math.max(backtest.model_mape, backtest.naive_mape, 0.01)

  function selectRow(skuId: string, area: string) {
    setSelection({ skuId, area })
  }

  function handleRowKeyDown(e: React.KeyboardEvent, skuId: string, area: string) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      selectRow(skuId, area)
    }
  }

  return (
    <div className="forecast-page">
      <section className="forecast-panel forecast-headline">
        <h1>Off by {modelPct} on average</h1>
        <p className="sub">
          Same hour last week is off by {naivePct}. Backtest over the last {backtest.horizon_days} days.
        </p>
        <div className="forecast-bars">
          <div className="forecast-bar-row">
            <span>Rio</span>
            <div className="forecast-bar-track">
              <div
                className="forecast-bar-fill ours"
                style={{ width: `${(backtest.model_mape / maxMape) * 100}%` }}
              />
            </div>
            <span className="num">{modelPct}</span>
          </div>
          <div className="forecast-bar-row">
            <span>Naive</span>
            <div className="forecast-bar-track">
              <div
                className="forecast-bar-fill naive"
                style={{ width: `${(backtest.naive_mape / maxMape) * 100}%` }}
              />
            </div>
            <span className="num">{naivePct}</span>
          </div>
        </div>
      </section>

      <section className="forecast-panel forecast-controls">
        <label>
          SKU
          <select
            className="field"
            value={selection?.skuId ?? ''}
            onChange={(e) => selectRow(e.target.value, selection?.area ?? summary.areas[0] ?? '')}
          >
            {summary.skus.map((s) => (
              <option key={s.sku_id} value={s.sku_id}>
                {s.brand_name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Area
          <select
            className="field"
            value={selection?.area ?? ''}
            onChange={(e) => selectRow(selection?.skuId ?? summary.skus[0]?.sku_id ?? '', e.target.value)}
          >
            {summary.areas.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </label>
      </section>

      <section className="forecast-panel forecast-chart-panel">
        <h2>Units per hour</h2>
        {seriesLoading && (
          <div className="forecast-status">
            <Dots label="Loading series" />
            <span>Loading series…</span>
          </div>
        )}
        {!seriesLoading && seriesError != null && (
          <div className="forecast-error">
            <p>{errorMessage(seriesError)}</p>
            <button
              type="button"
              className="btn"
              onClick={() => selection && setSelection({ ...selection })}
            >
              Retry
            </button>
          </div>
        )}
        {!seriesLoading && seriesError == null && series && (
          <>
            <ResponsiveContainer width="100%" height={300}>
              <ComposedChart data={chartData} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--line-2)" />
                <XAxis
                  dataKey="ts"
                  tickFormatter={formatTick}
                  minTickGap={40}
                  tick={{ fill: 'var(--muted)', fontSize: 12 }}
                />
                <YAxis tick={{ fill: 'var(--muted)', fontSize: 12 }} width={40} />
                <Tooltip
                  labelFormatter={(ts) => formatTick(String(ts))}
                  formatter={(value, name) => [
                    typeof value === 'number' ? value.toFixed(1) : '—',
                    name === 'actual' ? 'Actual' : 'Forecast',
                  ]}
                />
                {nowTs && endTs && nowTs !== endTs && (
                  <ReferenceArea x1={nowTs} x2={endTs} fill="var(--accent)" fillOpacity={0.06} />
                )}
                {nowTs && (
                  <ReferenceLine x={nowTs} stroke="var(--muted)" strokeDasharray="4 4" label={{ value: 'now', position: 'insideTopLeft', fill: 'var(--muted)', fontSize: 12 }} />
                )}
                <Line
                  type="monotone"
                  dataKey="actual"
                  name="actual"
                  stroke="var(--ink)"
                  strokeWidth={2}
                  dot={false}
                  connectNulls={false}
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="forecast"
                  name="forecast"
                  stroke="var(--accent)"
                  strokeWidth={2}
                  strokeDasharray="5 4"
                  dot={false}
                  connectNulls={false}
                  isAnimationActive={false}
                />
              </ComposedChart>
            </ResponsiveContainer>
            <div className="forecast-chart-footnote">
              <span>Model error: {formatPct(series.model_mape)}</span>
              <span>Naive error: {formatPct(series.naive_mape)}</span>
            </div>
          </>
        )}
      </section>

      <section className="forecast-panel forecast-table-panel">
        <div className="forecast-table-head">
          <h2>Reorder suggestions</h2>
          {riskCount > 0 && riskCount < summary.reorders.length && (
            <button type="button" className="btn btn-sm" onClick={() => setShowAll((v) => !v)}>
              {showAll ? `Show only the ${riskCount} at risk` : `Show all ${summary.reorders.length}`}
            </button>
          )}
        </div>
        <div className="forecast-table-scroll">
          <table className="forecast-table">
            <thead>
              <tr>
                <th>SKU</th>
                <th>Area</th>
                <th className="num">On hand</th>
                <th className="num">Demand over lead time</th>
                <th className="num">Runs out in</th>
                <th className="num">Reorder</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {tableRows.map((row) => {
                const isSelected =
                  selection?.skuId === row.sku_id && selection?.area === row.area
                const rowClass = [
                  'forecast-row',
                  row.stockout_risk ? 'risk' : '',
                  isSelected ? 'selected' : '',
                ]
                  .filter(Boolean)
                  .join(' ')
                return (
                  <tr
                    key={`${row.sku_id}-${row.area}`}
                    className={rowClass}
                    tabIndex={0}
                    onClick={() => selectRow(row.sku_id, row.area)}
                    onKeyDown={(e) => handleRowKeyDown(e, row.sku_id, row.area)}
                  >
                    <td>
                      <button
                        type="button"
                        className="forecast-row-btn"
                        tabIndex={-1}
                        onClick={() => selectRow(row.sku_id, row.area)}
                      >
                        {row.brand_name}
                      </button>
                    </td>
                    <td>{row.area}</td>
                    <td className="num">{row.on_hand}</td>
                    <td className="num">{row.forecast_over_lead_time.toFixed(1)}</td>
                    <td className="num">{formatHours(row.hours_to_stockout)}</td>
                    <td className={`num forecast-reorder-qty${row.reorder_qty > 0 ? ' qty-positive' : ''}`}>
                      {row.reorder_qty}
                    </td>
                    <td>
                      {row.stockout_risk ? (
                        <TriageBadge triage="red" label="Stockout risk" />
                      ) : (
                        <TriageBadge triage="green" label="OK" />
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
