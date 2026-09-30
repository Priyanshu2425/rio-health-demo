"""Demand forecast and reorder suggestions. Owned by `feat/data-forecast`.

The signatures below are the contract other branches call. Replace the bodies; do not
change the signatures without a contracts branch.
"""

from psycopg import AsyncConnection

from app.contracts import ForecastSummary, SkuForecast
from app.forecast import store as _store


async def get_summary(conn: AsyncConnection) -> ForecastSummary:
    """The latest stored run. Raises LookupError if no run exists yet."""
    return await _store.get_summary(conn)


async def get_sku_forecast(conn: AsyncConnection, sku_id: str, area: str) -> SkuForecast | None:
    return await _store.get_sku_forecast(conn, sku_id, area)


async def run(conn: AsyncConnection) -> ForecastSummary:
    """Recompute from synthetic_orders and inventory, store it, return the summary.

    Commits `conn` (the new run must be visible to other connections) and prunes
    forecast_runs to the latest 5 runs; their forecast_series rows cascade.
    """
    return await _store.run(conn)
