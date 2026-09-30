"""Samples come from the `samples` table. Needs RIO_HEALTH_DATABASE_URL and
`eval/load_samples.py` to have run; marked `db`, read-only."""

import io

import pytest
from PIL import Image
from psycopg import AsyncConnection

from app import parser
from app.core.config import get_settings

pytestmark = pytest.mark.db


@pytest.fixture
async def conn():
    s = get_settings()
    if not s.database_url:
        pytest.skip("RIO_HEALTH_DATABASE_URL not set")
    c = await AsyncConnection.connect(s.database_url, autocommit=True)
    await c.execute(f"SET search_path TO {s.db_schema}, public")
    await c.execute("SET default_transaction_read_only = on")
    yield c
    await c.close()


async def test_list_samples(conn):
    samples = await parser.list_samples(conn)
    assert [s.sample_id for s in samples][:3] == ["typed_clinic_3", "hospital_opd_4", "handwritten_style_3"]
    for s in samples:
        assert s.thumbnail_url == f"/api/samples/{s.sample_id}/image"
        assert s.label


async def test_load_every_sample(conn):
    for s in await parser.list_samples(conn):
        image, mime, parsed = await parser.load_sample(conn, s.sample_id)
        assert mime == "image/jpeg"
        Image.open(io.BytesIO(image)).verify()
        assert parsed.lines
        assert all(line.drug for line in parsed.lines)


async def test_unknown_sample(conn):
    with pytest.raises(KeyError):
        await parser.load_sample(conn, "nope")
