"""Eval-only, read-only stand-in for `app.catalog.search`.

`app.catalog` is owned by feat/data-forecast. Until it merges, `app.catalog.search`
raises NotImplementedError on this branch, so the eval patches in this adapter, which
runs the same kind of pg_trgm query against the `skus` table. It never writes: the
connection is set read-only. Once the real catalog lands, the eval uses it instead
(`--catalog auto`, the default).
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from app.contracts import SKU, MatchCandidate, Salt

SEARCH_SQL = """
WITH q AS (SELECT lower(%(q)s) AS q)
SELECT s.*,
       GREATEST(
           word_similarity(q.q, lower(s.brand_name)),
           similarity(q.q, lower(s.brand_name)),
           word_similarity(q.q, s.composition_key)
       ) AS score
FROM skus s, q
WHERE lower(s.brand_name) %% q.q
   OR q.q <%% lower(s.brand_name)
   OR q.q <%% s.composition_key
ORDER BY score DESC, s.mrp_inr ASC
LIMIT %(limit)s
"""


def row_to_sku(row: dict[str, Any]) -> SKU:
    composition = row["composition"] or []
    return SKU(
        sku_id=row["sku_id"],
        brand_name=row["brand_name"],
        manufacturer=row["manufacturer"],
        form=row["form"],
        pack_size=row["pack_size"],
        pack_label=row["pack_label"],
        mrp_inr=float(row["mrp_inr"]),
        composition=[Salt.model_validate(c) for c in composition],
        composition_key=row["composition_key"],
        rx_only=row["rx_only"],
        schedule=row["schedule"],
    )


async def search(conn: AsyncConnection, query: str, limit: int = 5) -> list[MatchCandidate]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(SEARCH_SQL, {"q": query, "limit": limit})
        rows = await cur.fetchall()
    return [MatchCandidate(sku=row_to_sku(r), score=min(1.0, float(r["score"]))) for r in rows]


async def connect_read_only(url: str, schema: str) -> AsyncConnection:
    conn = await AsyncConnection.connect(url, autocommit=True)
    await conn.execute(f"SET search_path TO {schema}, public")
    await conn.execute("SET default_transaction_read_only = on")
    return conn


async def sku_count(conn: AsyncConnection) -> int:
    try:
        cur = await conn.execute("SELECT count(*) FROM skus")
        row = await cur.fetchone()
        return int(row[0]) if row else 0
    except psycopg.Error:
        return 0
