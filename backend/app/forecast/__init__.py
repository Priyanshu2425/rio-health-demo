"""Demand forecast and reorder suggestions. Owned by `feat/data-forecast`.

The signatures below are the contract other branches call. Replace the bodies; do not
change the signatures without a contracts branch.
"""

import asyncio
from datetime import datetime

import numpy as np
import pandas as pd
from psycopg import AsyncConnection
from psycopg.rows import dict_row, tuple_row
from psycopg.types.json import Jsonb

from app.contracts import (
    BacktestSummary,
    ForecastPoint,
    ForecastSummary,
    ReorderSuggestion,
    SkuForecast,
    SkuRef,
)
from app.forecast import model
from app.forecast.synthetic import IST

KEEP_RUNS = 5


async def get_summary(conn: AsyncConnection) -> ForecastSummary:
    """The latest stored run. Raises LookupError if no run exists yet."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT summary FROM forecast_runs ORDER BY run_id DESC LIMIT 1")
        row = await cur.fetchone()
    if row is None:
        raise LookupError("no forecast run yet")
    return ForecastSummary.model_validate(row["summary"])


async def get_sku_forecast(conn: AsyncConnection, sku_id: str, area: str) -> SkuForecast | None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT series FROM forecast_series
            WHERE run_id = (SELECT max(run_id) FROM forecast_runs) AND sku_id = %s AND area = %s
            """,
            (sku_id, area),
        )
        row = await cur.fetchone()
    return SkuForecast.model_validate(row["series"]) if row else None


def _r(x: float, digits: int = 2) -> float:
    return round(max(0.0, float(x)), digits)


def compute(
    orders: pd.DataFrame,
    inventory: pd.DataFrame,
    brands: dict[str, str],
    generated_at: datetime,
) -> tuple[ForecastSummary, list[SkuForecast]]:
    """Pure part of `run`: orders (ts, area, sku_id, qty) + inventory -> summary and series."""
    if orders.empty:
        raise LookupError("synthetic_orders is empty; run scripts/etl/gen_orders.py")
    ts = pd.to_datetime(orders["ts"], utc=True).dt.tz_convert(IST)
    end = ts.max() + pd.Timedelta(hours=1)
    start = ts.min()
    series_by_key = model.to_hourly(orders, start.to_pydatetime(), end.to_pydatetime(), IST)
    stock = {(r.area, r.sku_id): r for r in inventory.itertuples(index=False)}

    forecasts: list[SkuForecast] = []
    reorders: list[ReorderSuggestion] = []
    model_errors, naive_errors = [], []
    for (area, sku_id), series in series_by_key.items():
        result = model.run_series(area, sku_id, series, end)
        model_errors.append(result.model_mape)
        naive_errors.append(result.naive_mape)
        points = [
            ForecastPoint(ts=t, forecast=_r(f), actual=_r(a))
            for t, f, a in zip(result.past_ts, result.past_forecast, result.past_actual, strict=True)
        ] + [
            ForecastPoint(ts=t, forecast=_r(f))
            for t, f in zip(result.future_ts, result.future_forecast, strict=True)
        ]
        brand = brands.get(sku_id, sku_id)
        forecasts.append(
            SkuForecast(
                sku_id=sku_id,
                brand_name=brand,
                area=area,
                points=points,
                model_mape=_r(result.model_mape, 4),
                naive_mape=_r(result.naive_mape, 4),
            )
        )
        inv = stock.get((area, sku_id))
        if inv is None:
            continue
        ro = model.reorder(int(inv.on_hand), result.future_forecast, int(inv.lead_time_hours))
        reorders.append(
            ReorderSuggestion(
                sku_id=sku_id,
                brand_name=brand,
                area=area,
                on_hand=int(inv.on_hand),
                forecast_over_lead_time=_r(ro.forecast_over_lead_time),
                reorder_qty=ro.reorder_qty,
                stockout_risk=ro.stockout_risk,
                hours_to_stockout=None if ro.hours_to_stockout is None else _r(ro.hours_to_stockout, 1),
            )
        )

    reorders.sort(
        key=lambda r: (
            not r.stockout_risk,
            r.hours_to_stockout if r.hours_to_stockout is not None else float("inf"),
            -r.reorder_qty,
            r.area,
            r.brand_name,
        )
    )
    sku_ids = sorted({f.sku_id for f in forecasts}, key=lambda s: brands.get(s, s).lower())
    summary = ForecastSummary(
        generated_at=generated_at,
        areas=sorted({f.area for f in forecasts}),
        skus=[SkuRef(sku_id=s, brand_name=brands.get(s, s)) for s in sku_ids],
        backtest=BacktestSummary(
            horizon_days=model.BACKTEST_DAYS,
            model_mape=_r(float(np.mean(model_errors)), 4),
            naive_mape=_r(float(np.mean(naive_errors)), 4),
        ),
        reorders=reorders,
    )
    return summary, forecasts


async def run(conn: AsyncConnection) -> ForecastSummary:
    """Recompute from synthetic_orders and inventory, store it, return the summary."""
    async with conn.cursor(row_factory=tuple_row) as cur:
        await cur.execute("SELECT ts, area, sku_id, qty FROM synthetic_orders")
        orders = pd.DataFrame(await cur.fetchall(), columns=["ts", "area", "sku_id", "qty"])
        await cur.execute("SELECT area, sku_id, on_hand, lead_time_hours FROM inventory")
        inventory = pd.DataFrame(
            await cur.fetchall(), columns=["area", "sku_id", "on_hand", "lead_time_hours"]
        )
        await cur.execute(
            "SELECT s.sku_id, s.brand_name FROM skus s "
            "WHERE s.sku_id IN (SELECT DISTINCT sku_id FROM inventory "
            "UNION SELECT DISTINCT sku_id FROM synthetic_orders)"
        )
        brands = dict(await cur.fetchall())

    generated_at = datetime.now(IST).replace(microsecond=0)
    # the model is CPU-bound for a few seconds; keep the event loop free
    summary, forecasts = await asyncio.to_thread(compute, orders, inventory, brands, generated_at)

    async with conn.transaction(), conn.cursor(row_factory=tuple_row) as cur:
        await cur.execute(
            "INSERT INTO forecast_runs (generated_at, summary) VALUES (%s, %s) RETURNING run_id",
            (generated_at, Jsonb(summary.model_dump(mode="json"))),
        )
        (run_id,) = await cur.fetchone()
        await cur.executemany(
            "INSERT INTO forecast_series (run_id, area, sku_id, series) VALUES (%s, %s, %s, %s)",
            [(run_id, f.area, f.sku_id, Jsonb(f.model_dump(mode="json"))) for f in forecasts],
        )
        await cur.execute(
            "DELETE FROM forecast_runs WHERE run_id NOT IN "
            "(SELECT run_id FROM forecast_runs ORDER BY run_id DESC LIMIT %s)",
            (KEEP_RUNS,),
        )
    if not conn.autocommit:
        # the SELECTs above opened a transaction, so the block was a savepoint
        await conn.commit()
    return summary
