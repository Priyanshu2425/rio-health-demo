"""Catalog lookups. Owned by `feat/data-forecast`.

The signatures below are the contract other branches call. Replace the bodies; do not
change the signatures without a contracts branch.
"""

from psycopg import AsyncConnection

from app.catalog import query as _query
from app.contracts import SKU, MatchCandidate


async def search(conn: AsyncConnection, query: str, limit: int = 5) -> list[MatchCandidate]:
    """Trigram search over brand name and composition, best first, scores in 0..1.

    Must find 'Augmentin 625' by brand and 'amoxicillin clavulanate 500/125' by
    composition, tolerating spelling variants such as amoxicillin/amoxycillin.
    """
    return await _query.search(conn, query, limit)


async def get_sku(conn: AsyncConnection, sku_id: str) -> SKU | None:
    return await _query.get_sku(conn, sku_id)


async def cheapest_generic(conn: AsyncConnection, sku: SKU) -> SKU | None:
    """Cheapest other SKU with the same `composition_key` and form, if it costs less."""
    return await _query.cheapest_generic(conn, sku)
