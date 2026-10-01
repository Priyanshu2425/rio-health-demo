"""The visitors upsert against the real table. Marked `db`; deletes only its own row."""

import secrets

import pytest
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from app.api.visitors import UPSERT
from app.core.config import get_settings

pytestmark = pytest.mark.db

EMAIL = f"test-{secrets.token_hex(4)}@example.com"


@pytest.fixture
async def conn():
    settings = get_settings()
    if not settings.database_url:
        pytest.skip("RIO_HEALTH_DATABASE_URL is not set")
    connection = await AsyncConnection.connect(settings.database_url, row_factory=dict_row)
    await connection.execute(f"SET search_path TO {settings.db_schema}, public")
    try:
        yield connection
    finally:
        await connection.rollback()
        await connection.execute("DELETE FROM visitors WHERE email = %s", (EMAIL,))
        await connection.commit()
        await connection.close()


async def test_repeat_visit_counts_once_per_email(conn):
    await conn.execute(UPSERT, (EMAIL,))
    await conn.execute(UPSERT, (EMAIL,))
    row = await (
        await conn.execute(
            "SELECT visits, first_seen <= last_seen AS ordered FROM visitors WHERE email = %s", (EMAIL,)
        )
    ).fetchone()
    assert row["visits"] == 2 and row["ordered"]
