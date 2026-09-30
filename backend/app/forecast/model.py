"""Seasonal-baseline forecast, backtest and reorder maths. Pure: numpy + pandas only.

forecast(hour) = profile[hour of week] x level

- profile: mean of the last 8 weeks at each of the 168 hours of the week
- level: 7-day EWMA of daily totals / the profile's total for the same 24 hours, over
  24 h blocks ending at the forecast origin. Dividing each day by the profile's total for
  that same day (rather than the weekly-average day) keeps a Sunday bump from being
  read as a rise in level.

The backtest re-forecasts each of the last 14 days from its own midnight and compares
daily totals with "same hour last week" (naive). Errors are MAPE on daily totals, so the
near-zero night hours don't blow it up.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

HOURS_PER_WEEK = 168
PROFILE_WEEKS = 8
LEVEL_SPAN_DAYS = 7
LEVEL_WINDOW_DAYS = 28
BACKTEST_DAYS = 14
CHART_PAST_DAYS = 7
CHART_FUTURE_HOURS = 48
REORDER_BUFFER = 1.2  # order 20% above the lead-time forecast


def hour_of_week(index: pd.DatetimeIndex) -> np.ndarray:
    """Monday 00:00 = 0 ... Sunday 23:00 = 167, in the index's own timezone."""
    return (index.dayofweek * 24 + index.hour).to_numpy()


def forecast(history: pd.Series, horizon: int) -> np.ndarray:
    """Forecast `horizon` hours after the last hour of `history` (hourly, contiguous)."""
    if len(history) == 0:
        return np.zeros(horizon)
    recent = history.iloc[-PROFILE_WEEKS * HOURS_PER_WEEK :]
    how = hour_of_week(recent.index)
    sums = np.bincount(how, weights=recent.to_numpy(dtype=float), minlength=HOURS_PER_WEEK)
    counts = np.bincount(how, minlength=HOURS_PER_WEEK)
    profile = np.divide(sums, counts, out=np.zeros(HOURS_PER_WEEK), where=counts > 0)
    if profile.sum() <= 0:
        return np.zeros(horizon)

    n_days = min(LEVEL_WINDOW_DAYS, len(history) // 24)
    tail = history.iloc[len(history) - n_days * 24 :]
    actual = tail.to_numpy(dtype=float).reshape(n_days, 24).sum(axis=1)
    expected = profile[hour_of_week(tail.index)].reshape(n_days, 24).sum(axis=1)
    ratios = pd.Series(np.divide(actual, expected, out=np.ones(n_days), where=expected > 0))
    level = ratios.ewm(span=LEVEL_SPAN_DAYS, adjust=False).mean().iloc[-1]

    start = history.index[-1] + pd.Timedelta(hours=1)
    future = pd.date_range(start, periods=horizon, freq="h", tz=history.index.tz)
    return profile[hour_of_week(future)] * level


def mape(forecasts: list[float], actuals: list[float]) -> float:
    pairs = [(f, a) for f, a in zip(forecasts, actuals, strict=True) if a > 0]
    if not pairs:
        return 0.0
    return float(np.mean([abs(f - a) / a for f, a in pairs]))


@dataclass
class SeriesResult:
    area: str
    sku_id: str
    model_mape: float
    naive_mape: float
    past_ts: list[datetime]
    past_forecast: list[float]
    past_actual: list[float]
    future_ts: list[datetime]
    future_forecast: list[float]


def midnight(ts: pd.Timestamp) -> pd.Timestamp:
    return ts.normalize()


def evaluate(series: pd.Series, end: pd.Timestamp) -> tuple[float, float, np.ndarray, np.ndarray]:
    """Backtest the last BACKTEST_DAYS complete days before `end`.

    Returns model MAPE, naive MAPE, and hourly one-day-ahead forecasts plus actuals for
    every hour from `end - CHART_PAST_DAYS` to `end` (each hour forecast from the midnight
    that starts its day), for the chart.
    """
    today = midnight(end)
    model_daily, naive_daily, actual_daily = [], [], []
    for back in range(BACKTEST_DAYS, 0, -1):
        origin = today - pd.Timedelta(days=back)
        history = series[series.index < origin]
        day = series[(series.index >= origin) & (series.index < origin + pd.Timedelta(days=1))]
        last_week = series[
            (series.index >= origin - pd.Timedelta(days=7)) & (series.index < origin - pd.Timedelta(days=6))
        ]
        model_daily.append(float(forecast(history, 24).sum()))
        naive_daily.append(float(last_week.sum()))
        actual_daily.append(float(day.sum()))

    chart_start = end - pd.Timedelta(days=CHART_PAST_DAYS)
    past = series[(series.index >= chart_start) & (series.index < end)]
    past_fc = np.zeros(len(past))
    for origin in sorted({midnight(ts) for ts in past.index}):
        history = series[series.index < origin]
        fc = forecast(history, 24)
        mask = (past.index >= origin) & (past.index < origin + pd.Timedelta(days=1))
        offsets = ((past.index[mask] - origin) / pd.Timedelta(hours=1)).astype(int)
        past_fc[mask] = fc[offsets]
    return (
        mape(model_daily, actual_daily),
        mape(naive_daily, actual_daily),
        past_fc,
        past.to_numpy(dtype=float),
    )


def run_series(area: str, sku_id: str, series: pd.Series, end: pd.Timestamp) -> SeriesResult:
    """`series`: hourly demand, IST, contiguous, zeros filled, last hour = end - 1h."""
    model_mape, naive_mape, past_fc, past_actual = evaluate(series, end)
    future = forecast(series[series.index < end], CHART_FUTURE_HOURS)
    past_index = series.index[
        (series.index >= end - pd.Timedelta(days=CHART_PAST_DAYS)) & (series.index < end)
    ]
    return SeriesResult(
        area=area,
        sku_id=sku_id,
        model_mape=model_mape,
        naive_mape=naive_mape,
        past_ts=[ts.to_pydatetime() for ts in past_index],
        past_forecast=[float(x) for x in past_fc],
        past_actual=[float(x) for x in past_actual],
        future_ts=[(end + pd.Timedelta(hours=h)).to_pydatetime() for h in range(CHART_FUTURE_HOURS)],
        future_forecast=[float(x) for x in future],
    )


@dataclass
class Reorder:
    forecast_over_lead_time: float
    reorder_qty: int
    stockout_risk: bool
    hours_to_stockout: float | None


def reorder(on_hand: int, hourly_forecast: list[float] | np.ndarray, lead_time_hours: int) -> Reorder:
    """Order enough to cover the lead time plus a 20% buffer; flag a stockout inside it.

    reorder_qty = max(0, ceil(forecast_over_lead_time x 1.2 - on_hand)). The hours to
    stockout are interpolated inside the hour where cumulative demand reaches on-hand,
    and are null when stock outlasts the forecast horizon.
    """
    fc = np.asarray(hourly_forecast, dtype=float)
    over_lead = float(fc[:lead_time_hours].sum())
    qty = max(0, math.ceil(round(over_lead * REORDER_BUFFER - on_hand, 6)))
    hours: float | None = None
    if on_hand <= 0:
        hours = 0.0
    else:
        cum = 0.0
        for i, f in enumerate(fc):
            if f > 0 and cum + f >= on_hand:
                hours = float(i + (on_hand - cum) / f)
                break
            cum += float(f)
    risk = bool(hours is not None and hours < lead_time_hours)
    return Reorder(
        forecast_over_lead_time=over_lead,
        reorder_qty=qty,
        stockout_risk=risk,
        hours_to_stockout=hours,
    )


def to_hourly(frame: pd.DataFrame, start: datetime, end: datetime, tz) -> dict[tuple[str, str], pd.Series]:
    """Rows (ts, area, sku_id, qty) -> one contiguous hourly series per (area, sku_id)."""
    index = pd.date_range(start, end - timedelta(hours=1), freq="h", tz=tz)
    out: dict[tuple[str, str], pd.Series] = {}
    if frame.empty:
        return out
    frame = frame.assign(ts=pd.to_datetime(frame["ts"], utc=True).dt.tz_convert(tz))
    for (area, sku), group in frame.groupby(["area", "sku_id"], sort=True):
        series = group.set_index("ts")["qty"].astype(float)
        series = series.groupby(level=0).sum().reindex(index, fill_value=0.0)
        out[(area, sku)] = series
    return out
