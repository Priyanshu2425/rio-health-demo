"""Forecast run and reads against the real schema (data from scripts/etl/gen_orders.py).

One test, because `run` takes several seconds against Neon.
"""

import pytest

from app.contracts import ForecastSummary, SkuForecast
from app.forecast import get_sku_forecast, get_summary, run

pytestmark = pytest.mark.db


async def test_run_then_read_back(conn):
    cur = await conn.execute("SELECT count(*) AS n FROM synthetic_orders")
    if (await cur.fetchone())["n"] == 0:
        pytest.skip("no synthetic orders; run scripts/etl/gen_orders.py")

    summary = await run(conn)
    assert isinstance(summary, ForecastSummary)

    stored = await get_summary(conn)
    assert stored.generated_at == summary.generated_at
    assert stored.backtest == summary.backtest
    assert stored.backtest.model_mape < stored.backtest.naive_mape
    assert any(r.stockout_risk for r in stored.reorders)
    assert all(r.reorder_qty >= 0 for r in stored.reorders)
    assert {"sku_dolo_650", "sku_electral_21g", "sku_pan_40"} <= {s.sku_id for s in stored.skus}

    ref = stored.skus[0]
    series = await get_sku_forecast(conn, ref.sku_id, stored.areas[0])
    assert isinstance(series, SkuForecast)
    assert series.sku_id == ref.sku_id
    assert sum(p.actual is None for p in series.points) == 48
    assert await get_sku_forecast(conn, "sku_does_not_exist", "Area A") is None
