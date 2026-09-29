"""One async connection pool for the process.

Use the direct (non-pooled) Neon endpoint: the pool sets `search_path` at connect time,
which PgBouncer's transaction mode would drop.
"""

from collections.abc import AsyncIterator

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.core.config import get_settings

_pool: AsyncConnectionPool | None = None


async def _configure(conn: AsyncConnection) -> None:
    schema = get_settings().db_schema
    await conn.execute(f"SET search_path TO {schema}, public")
    await conn.commit()


async def open_pool() -> None:
    global _pool
    url = get_settings().database_url
    if url is None:
        raise RuntimeError("RIO_HEALTH_DATABASE_URL is not set")
    _pool = AsyncConnectionPool(
        url,
        min_size=1,
        max_size=5,
        open=False,
        configure=_configure,
        kwargs={"row_factory": dict_row},
    )
    await _pool.open()


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def get_conn() -> AsyncIterator[AsyncConnection]:
    """FastAPI dependency: `conn: AsyncConnection = Depends(get_conn)`."""
    if _pool is None:
        raise RuntimeError("database pool is not open")
    async with _pool.connection() as conn:
        yield conn
