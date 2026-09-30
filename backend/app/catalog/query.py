"""Catalog queries behind the contract functions in `app.catalog`."""

import re
from typing import Any

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row

from app.catalog.normalize import normalize_query
from app.contracts import SKU, MatchCandidate

COLUMNS = (
    "sku_id, brand_name, manufacturer, form, pack_size, pack_label, mrp_inr, "
    "composition, composition_key, rx_only, schedule"
)

# Candidates come from the GIN trigram indexes: `<%` (word similarity, pg_trgm default
# threshold 0.6) finds brands and compositions that contain the query, and `%`
# (similarity, default 0.3) catches misspelt brands such as 'augmantin'. The defaults
# are used as they are, so search never changes a connection setting. The score is the
# better of brand and composition, each the mean of similarity() and word_similarity(),
# so it lies in 0..1. Equal scores (e.g. every SKU of one composition) go to the
# better-known brand (`popularity_rank`, written by the catalog ETL), then the lower
# price per unit.
SEARCH_SQL = """
WITH cand AS (
    SELECT sku_id FROM skus WHERE {q} <% lower(brand_name)
    UNION
    SELECT sku_id FROM skus WHERE lower(brand_name) % {q}
    UNION
    SELECT sku_id FROM skus WHERE {q} <% composition_key
)
SELECT * FROM (
    SELECT {columns}, popularity_rank,
        greatest(
            (similarity(lower(brand_name), {q}) + word_similarity({q}, lower(brand_name))) / 2,
            (similarity(composition_key, {q}) + word_similarity({q}, composition_key)) / 2
        ) AS score
    FROM skus JOIN cand USING (sku_id)
) scored
ORDER BY round(score::numeric, 4) DESC, popularity_rank NULLS LAST, mrp_inr / pack_size, sku_id
LIMIT {limit}
"""

# Same guard as the ETL: listings under a fifth of the median unit price for their
# composition and form are almost always data errors, so never offer one as the generic
# (only applied when the group has at least 3 SKUs).
PRICE_FLOOR = 0.2
GENERIC_SQL = f"""
WITH grp AS (
    SELECT count(*) AS n,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY mrp_inr / pack_size) AS median_unit
    FROM skus WHERE composition_key = %(key)s AND form = %(form)s
)
SELECT {COLUMNS} FROM skus, grp
WHERE composition_key = %(key)s AND form = %(form)s AND sku_id <> %(id)s
  AND mrp_inr * %(pack)s < %(mrp)s::numeric * pack_size
  AND (grp.n < 3 OR mrp_inr / pack_size >= {PRICE_FLOOR} * grp.median_unit)
ORDER BY mrp_inr / pack_size, mrp_inr, sku_id
LIMIT 50
"""

_AMOUNT = re.compile(r"(\d+(?:\.\d+)?)\s*(ml|gm|g|mg|mcg|mdi|l|ltr)\b")


def pack_amount(pack_label: str) -> tuple[float, str] | None:
    """'bottle of 15 ml oral drops' -> (15.0, 'ml'); None when there is no measured amount."""
    match = _AMOUNT.search(pack_label.lower())
    if match is None:
        return None
    unit = {"g": "gm", "ltr": "l"}.get(match.group(2), match.group(2))
    return float(match.group(1)), unit


def same_whole_pack(a: SKU, b: SKU) -> bool:
    """For one-unit packs (bottles, tubes, sachets, inhalers), is b the same size as a?"""
    amount_a, amount_b = pack_amount(a.pack_label), pack_amount(b.pack_label)
    if amount_a is None or amount_b is None:
        return a.pack_label == b.pack_label
    return amount_a == amount_b


def to_sku(row: dict[str, Any]) -> SKU:
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


async def search(conn: AsyncConnection, query: str, limit: int) -> list[MatchCandidate]:
    q = normalize_query(query)
    limit = max(1, min(limit, 50))
    if not q:
        return []
    statement = sql.SQL(SEARCH_SQL).format(
        q=sql.Literal(q), columns=sql.SQL(COLUMNS), limit=sql.Literal(limit)
    )
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(statement)
        rows = await cur.fetchall()
    return [
        MatchCandidate(sku=to_sku(row), score=min(1.0, max(0.0, round(float(row["score"]), 4))))
        for row in rows
    ]


async def get_sku(conn: AsyncConnection, sku_id: str) -> SKU | None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(f"SELECT {COLUMNS} FROM skus WHERE sku_id = %s", (sku_id,))
        row = await cur.fetchone()
    return to_sku(row) if row else None


async def cheapest_generic(conn: AsyncConnection, sku: SKU) -> SKU | None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            GENERIC_SQL,
            {
                "key": sku.composition_key,
                "form": sku.form,
                "id": sku.sku_id,
                "pack": sku.pack_size,
                "mrp": str(sku.mrp_inr),
            },
        )
        rows = await cur.fetchall()
    for row in rows:
        candidate = to_sku(row)
        # a one-unit pack is only comparable with the same bottle / tube size, or a
        # 15 ml bottle would look like a cheaper generic of a 60 ml one
        if sku.pack_size == 1 and not same_whole_pack(sku, candidate):
            continue
        return candidate
    return None
