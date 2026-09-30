"""Print catalog row counts and a few sample searches, for docs/verify.

cd backend && PYTHONPATH=. uv run python ../scripts/etl/sample_search.py ["query" ...]
"""

import asyncio
import sys
import time

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from app.catalog import cheapest_generic, search
from app.core.config import get_settings

DEFAULT_QUERIES = ["augmentin 625", "amoxicillin clavulanate 500/125", "pan 40", "dolo 650"]


async def main(queries: list[str]) -> None:
    settings = get_settings()
    async with await AsyncConnection.connect(settings.database_url, row_factory=dict_row) as conn:
        await conn.execute(f"SET search_path TO {settings.db_schema}, public")
        cur = await conn.execute(
            "SELECT count(*) AS n, count(DISTINCT composition_key) AS keys, "
            "round(avg(rx_only::int) * 100, 1) AS rx_pct FROM skus"
        )
        stats = await cur.fetchone()
        print(f"skus: {stats['n']} rows, {stats['keys']} composition keys, rx_only {stats['rx_pct']}%")
        for q in queries:
            started = time.perf_counter()
            results = await search(conn, q, limit=3)
            ms = (time.perf_counter() - started) * 1000
            print(f"\nsearch {q!r} ({ms:.0f} ms incl. network)")
            for r in results:
                s = r.sku
                rx = f"Rx {s.schedule}" if s.rx_only else "OTC"
                print(
                    f"  {r.score:.2f}  {s.sku_id:<24} {s.brand_name:<20} {s.composition_key}  ₹{s.mrp_inr} {rx}"
                )
            if results:
                generic = await cheapest_generic(conn, results[0].sku)
                if generic:
                    print(
                        f"  generic for top hit: {generic.brand_name} ₹{generic.mrp_inr} / {generic.pack_label}"
                    )


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or DEFAULT_QUERIES))
