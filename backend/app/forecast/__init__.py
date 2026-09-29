"""Demand forecast and reorder suggestions. Owned by `feat/data-forecast`.

The signatures below are the contract other branches call. Replace the bodies; do not
change the signatures without a contracts branch.
"""

from psycopg import AsyncConnection

from app.contracts import ForecastSummary, SkuForecast


async def get_summary(conn: AsyncConnection) -> ForecastSummary:
    """The latest stored run. Raises LookupError if no run exists yet."""
    raise NotImplementedError


async def get_sku_forecast(conn: AsyncConnection, sku_id: str, area: str) -> SkuForecast | None:
    raise NotImplementedError


async def run(conn: AsyncConnection) -> ForecastSummary:
    """Recompute from synthetic_orders and inventory, store it, return the summary."""
    raise NotImplementedError
