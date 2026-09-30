"""Which catalog / parser / forecast / storage the API talks to.

Real mode (RIO_USE_MOCKS=0) calls the real modules through the signatures in their
__init__.py and stores orders in Postgres. It needs the database: app startup fails if
RIO_HEALTH_DATABASE_URL is missing or the pool cannot open, and there is no fallback.

Mock mode (RIO_USE_MOCKS=1) is for development only: every cross-module call goes to
app.orders.mocks and orders live in memory.
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


class _State:
    database = False  # set by the app lifespan once the pool is open


state = _State()


def uses_database() -> bool:
    return state.database


def modules() -> Modules:
    return MOCK if get_settings().use_mocks else REAL


def orders() -> OrderRepo:
    if get_settings().use_mocks:
        return memory_orders
    if not state.database:
        raise RuntimeError("real mode needs the database, but the pool is not open")
    return postgres_orders


async def get_conn() -> AsyncIterator[Any]:
    """FastAPI dependency: a pooled connection, or None in mock mode."""
    if get_settings().use_mocks:
        yield None
        return
    async for conn in db.get_conn():
        yield conn
