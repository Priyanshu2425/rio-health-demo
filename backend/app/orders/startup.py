"""Startup work for real mode: open the database, and make sure a forecast exists."""

from __future__ import annotations

import asyncio
import logging
from contextlib import aclosing

from app import forecast
from app.core import db
from app.core.config import Settings
from app.orders.deps import state

log = logging.getLogger("rio.startup")


async def open_database(settings: Settings) -> None:
    """Real mode needs the database; fail startup loudly rather than fall back."""
    if not settings.database_url:
        raise RuntimeError(
            "RIO_USE_MOCKS=0 needs RIO_HEALTH_DATABASE_URL. Set it, or set RIO_USE_MOCKS=1 for "
            "local development against fixtures."
        )
    try:
        await db.open_pool()
    except Exception as exc:
        raise RuntimeError(f"could not open the database pool: {exc}") from exc
    state.database = True


async def close_database() -> None:
    state.database = False
    await db.close_pool()


async def ensure_forecast() -> None:
    """If forecast_runs is empty, compute the first run (about 17 s). Never raises."""
    try:
        # aclosing: the early return below must still hand the connection back to the pool.
        async with aclosing(db.get_conn()) as conns:
            async for conn in conns:
                cur = await conn.execute("SELECT EXISTS (SELECT 1 FROM forecast_runs) AS has_run")
                row = await cur.fetchone()
                await conn.commit()
                if row["has_run"]:
                    return
                log.info("forecast_runs is empty; running the first forecast in the background")
                summary = await forecast.run(conn)
                log.info("first forecast stored: %d reorder suggestions", len(summary.reorders))
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("startup forecast run failed; /api/forecast/* answers no_forecast until restart")


def start_forecast_task() -> asyncio.Task[None]:
    return asyncio.create_task(ensure_forecast(), name="startup-forecast")
