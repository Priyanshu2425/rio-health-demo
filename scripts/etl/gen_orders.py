"""Generate 90 days of synthetic hourly orders and inventory, then run the forecast.

    cd backend && PYTHONPATH=. uv run python ../scripts/etl/gen_orders.py [--no-forecast]

The data is synthetic; see README.md for the structure injected. The random seed is
fixed, so the same end hour always produces the same orders. Needs `skus` loaded first
(build_catalog.py). Replaces synthetic_orders and inventory in one transaction.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

from common import connect
from psycopg import AsyncConnection

from app.core.config import get_settings
from app.forecast import run
from app.forecast.synthetic import AREAS, PLAN, end_of_history, generate


def write(data) -> None:
    demand = data.demand
    with connect() as conn, conn.transaction():
        wanted = [sku for sku, _ in PLAN]
        found = {r[0] for r in conn.execute("SELECT sku_id FROM skus WHERE sku_id = ANY(%s)", (wanted,))}
        missing = sorted(set(wanted) - found)
        if missing:
            raise SystemExit(f"SKUs missing from skus (run build_catalog.py first): {', '.join(missing)}")
        conn.execute("TRUNCATE synthetic_orders, inventory")
        rows = 0
        with conn.cursor().copy("COPY synthetic_orders (ts, area, sku_id, qty) FROM STDIN") as copy:
            for area, sku in demand.columns:
                col = demand[(area, sku)]
                for ts, qty in col[col > 0].items():
                    copy.write_row((ts.to_pydatetime(), area, sku, int(qty)))
                    rows += 1
        with conn.cursor().copy("COPY inventory (area, sku_id, on_hand, lead_time_hours) FROM STDIN") as copy:
            for rec in data.inventory.itertuples(index=False):
                copy.write_row((rec.area, rec.sku_id, int(rec.on_hand), int(rec.lead_time_hours)))
    print(
        f"synthetic_orders: {rows:,} non-zero hourly rows ({int(demand.to_numpy().sum()):,} packs), "
        f"{len(PLAN)} SKUs x {len(AREAS)} areas, {demand.index[0]:%Y-%m-%d %H:%M} to "
        f"{demand.index[-1]:%Y-%m-%d %H:%M} IST"
    )
    print(f"inventory: {len(data.inventory)} rows, {len(data.low_stock)} seeded low")


async def forecast() -> None:
    settings = get_settings()
    async with await AsyncConnection.connect(settings.database_url) as conn:
        await conn.execute(f"SET search_path TO {settings.db_schema}, public")
        started = time.perf_counter()
        summary = await run(conn)
    risks = [r for r in summary.reorders if r.stockout_risk]
    print(
        f"forecast run: backtest {summary.backtest.horizon_days} days, model MAPE "
        f"{summary.backtest.model_mape:.1%} vs naive {summary.backtest.naive_mape:.1%}; "
        f"{len(risks)} stockout risks of {len(summary.reorders)} ({time.perf_counter() - started:.1f}s)"
    )
    for r in risks[:5]:
        print(
            f"  {r.area} {r.brand_name}: on hand {r.on_hand}, next 24h {r.forecast_over_lead_time}, "
            f"out in {r.hours_to_stockout} h, reorder {r.reorder_qty}"
        )


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-forecast", action="store_true", help="skip the forecast run")
    args = parser.parse_args(argv)
    data = generate(end_of_history())
    write(data)
    if not args.no_forecast:
        asyncio.run(forecast())


if __name__ == "__main__":
    main(sys.argv[1:])
