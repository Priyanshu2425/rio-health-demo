"""Which catalog / parser / forecast / storage the API talks to.

Mock mode (RIO_USE_MOCKS=1) routes every cross-module call to app.orders.mocks and
keeps orders in memory. Otherwise the real modules are called through the signatures in
their __init__.py, and orders go to Postgres when a pool is open.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from app import catalog as real_catalog
from app import forecast as real_forecast
from app import parser as real_parser
from app.core import db
from app.core.config import get_settings
from app.orders import mocks
from app.orders.repo import OrderRepo, memory_orders, postgres_orders


@dataclass(frozen=True)
class Modules:
    catalog: Any
    parser: Any
    forecast: Any


MOCK = Modules(catalog=mocks.catalog, parser=mocks.parser, forecast=mocks.forecast)
REAL = Modules(catalog=real_catalog, parser=real_parser, forecast=real_forecast)


def uses_database() -> bool:
    return not get_settings().use_mocks and db._pool is not None


def modules() -> Modules:
    return MOCK if get_settings().use_mocks else REAL


def orders() -> OrderRepo:
    return postgres_orders if uses_database() else memory_orders


async def get_conn() -> AsyncIterator[Any]:
    """FastAPI dependency: a pooled connection, or None in mock / no-database mode."""
    if not uses_database():
        yield None
        return
    async for conn in db.get_conn():
        yield conn
