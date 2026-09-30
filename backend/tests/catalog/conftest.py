import pytest
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from app.core.config import get_settings


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
        await connection.close()
