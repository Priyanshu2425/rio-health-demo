"""Catalog lookups. Owned by `feat/data-forecast`.

The signatures below are the contract other branches call. Replace the bodies; do not
change the signatures without a contracts branch.
"""

from typing import Any

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row

from app.catalog.normalize import normalize_query
from app.catalog.popularity import popularity_rank
from app.contracts import SKU, MatchCandidate

_COLUMNS = (
    "sku_id, brand_name, manufacturer, form, pack_size, pack_label, mrp_inr, "
    "composition, composition_key, rx_only, schedule"
)

# Trigram candidates come from the GIN indexes via `<%` (word similarity above the
# threshold); the score is then the better of brand and composition, each the mean of
# similarity() and word_similarity(), so both lie in 0..1.
_WORD_SIM_THRESHOLD = 0.5
_SEARCH_SQL = """
SELECT set_config('pg_trgm.word_similarity_threshold', {threshold}, false);
WITH cand AS (
    SELECT sku_id FROM skus WHERE {q} <% lower(brand_name)
    UNION
    SELECT sku_id FROM skus WHERE {q} <% composition_key
)
SELECT {columns},
    greatest(
        (similarity(lower(brand_name), {q}) + word_similarity({q}, lower(brand_name))) / 2,
        (similarity(composition_key, {q}) + word_similarity({q}, composition_key)) / 2
    ) AS score
FROM skus JOIN cand USING (sku_id)
ORDER BY score DESC
LIMIT {pool}
"""


def _to_sku(row: dict[str, Any]) -> SKU:
    return SKU(
        sku_id=row["sku_id"],
        brand_name=row["brand_name"],
        manufacturer=row["manufacturer"],
        form=row["form"],
        pack_size=row["pack_size"],
        pack_label=row["pack_label"],
        mrp_inr=float(row["mrp_inr"]),
        composition=row["composition"],
        composition_key=row["composition_key"],
        rx_only=row["rx_only"],
        schedule=row["schedule"],
    )


async def search(conn: AsyncConnection, query: str, limit: int = 5) -> list[MatchCandidate]:
    """Trigram search over brand name and composition, best first, scores in 0..1.

    Must find 'Augmentin 625' by brand and 'amoxicillin clavulanate 500/125' by
    composition, tolerating spelling variants such as amoxicillin/amoxycillin.
    """
    q = normalize_query(query)
    limit = max(1, min(limit, 50))
    if not q:
        return []
    statement = sql.SQL(_SEARCH_SQL).format(
        threshold=sql.Literal(str(_WORD_SIM_THRESHOLD)),
        q=sql.Literal(q),
        columns=sql.SQL(_COLUMNS),
        pool=sql.Literal(max(limit * 4, 20)),
    )
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(statement)
        cur.nextset()
        rows = await cur.fetchall()

    ranks = popularity_rank()
    worst = len(ranks) + 1

    def order(row: dict[str, Any]) -> tuple:
        # equal scores (e.g. every SKU of one composition) go to the better-known brand,
        # then to the lower price per unit
        unit_price = float(row["mrp_inr"]) / row["pack_size"]
        return (-round(float(row["score"]), 4), ranks.get(row["sku_id"], worst), unit_price)

    rows.sort(key=order)
    return [
        MatchCandidate(sku=_to_sku(row), score=min(1.0, max(0.0, round(float(row["score"]), 4))))
        for row in rows[:limit]
    ]


async def get_sku(conn: AsyncConnection, sku_id: str) -> SKU | None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(f"SELECT {_COLUMNS} FROM skus WHERE sku_id = %s", (sku_id,))
        row = await cur.fetchone()
    return _to_sku(row) if row else None


async def cheapest_generic(conn: AsyncConnection, sku: SKU) -> SKU | None:
    """Cheapest other SKU with the same `composition_key` and form, if it costs less.

    "Costs less" compares price per unit (MRP / pack size), since packs differ in size.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            f"""
            SELECT {_COLUMNS} FROM skus
            WHERE composition_key = %(key)s AND form = %(form)s AND sku_id <> %(id)s
              AND mrp_inr * %(pack)s < %(mrp)s::numeric * pack_size
            ORDER BY mrp_inr / pack_size, mrp_inr, sku_id
            LIMIT 1
            """,
            {
                "key": sku.composition_key,
                "form": sku.form,
                "id": sku.sku_id,
                "pack": sku.pack_size,
                "mrp": str(sku.mrp_inr),
            },
        )
        row = await cur.fetchone()
    return _to_sku(row) if row else None
