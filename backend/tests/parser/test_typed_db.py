"""Typed requests against the real catalog. Needs RIO_HEALTH_DATABASE_URL; marked `db`,
read-only, and never calls the re-rank model."""

import pytest
from psycopg import AsyncConnection

from app import parser
from app.core.config import get_settings

pytestmark = pytest.mark.db


@pytest.fixture
async def conn(monkeypatch):
    s = get_settings()
    if not s.database_url:
        pytest.skip("RIO_HEALTH_DATABASE_URL not set")
    monkeypatch.setattr(s, "rerank_model", "")
    c = await AsyncConnection.connect(s.database_url, autocommit=True)
    await c.execute(f"SET search_path TO {s.db_schema}, public")
    await c.execute("SET default_transaction_read_only = on")
    yield c
    await c.close()


@pytest.mark.parametrize(
    ("typed", "brand"),
    [("dolo", "Dolo 650"), ("dolo 650", "Dolo 650"), ("crocin", "Crocin 650"), ("allegra", "Allegra 120mg")],
)
async def test_typed_brand_resolves_to_the_everyday_tablet(conn, typed, brand):
    [(_, result)] = await parser.match_text(conn, typed)
    assert result.sku is not None and result.sku.brand_name == brand
