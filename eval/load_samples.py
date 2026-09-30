"""Load the demo samples into the `samples` table (idempotent upsert).

    cd backend && uv run python ../eval/load_samples.py

Reads eval/samples/manifest.json (order = display position), each sample's image and
its cached ParsedRx JSON, validates the parse against the contract, and upserts one row
per sample. The running app reads only the table; these files are ETL input. Rows for
samples no longer in the manifest are left alone (delete them by hand if needed).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL_DIR.parent / "backend"))

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from app.contracts import ParsedRx
from app.core.config import get_settings

SAMPLES_DIR = EVAL_DIR / "samples"

UPSERT = """
INSERT INTO samples (sample_id, label, position, image, image_mime, parsed_rx)
VALUES (%(sample_id)s, %(label)s, %(position)s, %(image)s, %(image_mime)s, %(parsed_rx)s)
ON CONFLICT (sample_id) DO UPDATE SET
    label = EXCLUDED.label,
    position = EXCLUDED.position,
    image = EXCLUDED.image,
    image_mime = EXCLUDED.image_mime,
    parsed_rx = EXCLUDED.parsed_rx
"""


def manifest() -> list[dict]:
    return json.loads((SAMPLES_DIR / "manifest.json").read_text())


async def connect() -> AsyncConnection:
    s = get_settings()
    if not s.database_url:
        raise SystemExit("RIO_HEALTH_DATABASE_URL is not set")
    conn = await AsyncConnection.connect(s.database_url, autocommit=True)
    await conn.execute(f"SET search_path TO {s.db_schema}, public")
    return conn


async def upsert_sample(conn: AsyncConnection, entry: dict, position: int, parsed: ParsedRx) -> None:
    await conn.execute(
        UPSERT,
        {
            "sample_id": entry["sample_id"],
            "label": entry["label"],
            "position": position,
            "image": (SAMPLES_DIR / entry["image"]).read_bytes(),
            "image_mime": entry["mime"],
            "parsed_rx": Jsonb(parsed.model_dump(mode="json")),
        },
    )


async def main_async() -> int:
    conn = await connect()
    try:
        for position, entry in enumerate(manifest(), start=1):
            parsed = ParsedRx.model_validate_json((SAMPLES_DIR / f"{entry['sample_id']}.json").read_text())
            await upsert_sample(conn, entry, position, parsed)
            print(f"{position}. {entry['sample_id']}: {len(parsed.lines)} lines ({parsed.model})")
        cur = await conn.execute("SELECT count(*) FROM samples")
        print(f"samples rows: {(await cur.fetchone())[0]}")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
