"""Demo prescriptions with cached parses: the 'try a sample' fallback.

Read from the `samples` table (migration 002). The images and parses in `eval/samples/`
are ETL input only, loaded by `eval/load_samples.py`; nothing here opens a file.
"""

from __future__ import annotations

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from app.contracts import ParsedRx, Sample


def thumbnail_url(sample_id: str) -> str:
    return f"/api/samples/{sample_id}/image"


async def list_samples(conn: AsyncConnection) -> list[Sample]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT sample_id, label FROM samples ORDER BY position, sample_id")
        rows = await cur.fetchall()
    return [
        Sample(sample_id=r["sample_id"], label=r["label"], thumbnail_url=thumbnail_url(r["sample_id"]))
        for r in rows
    ]


async def load_sample(conn: AsyncConnection, sample_id: str) -> tuple[bytes, str, ParsedRx]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT image, image_mime, parsed_rx FROM samples WHERE sample_id = %s", (sample_id,)
        )
        row = await cur.fetchone()
    if row is None:
        raise KeyError(sample_id)
    return bytes(row["image"]), row["image_mime"], ParsedRx.model_validate(row["parsed_rx"])
