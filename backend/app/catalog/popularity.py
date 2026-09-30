"""Brand popularity, used only to break ties between equally scored search results.

The committed seed `data/seed/skus.csv.gz` is written in popularity order (see
`scripts/etl/build_catalog.py`), so a SKU's row number there is its rank. The `skus`
table has no popularity column, and the schema is frozen, so the rank is read from the
seed once per process. Without the file every SKU ties and search falls back to price.

The first read gunzips about 9k rows; `warm()` does it up front (call it at startup),
and `load_popularity()` does it off the event loop if nobody has.
"""

import asyncio
import csv
import gzip
from functools import lru_cache
from pathlib import Path

SEED = Path(__file__).resolve().parents[3] / "data" / "seed" / "skus.csv.gz"


@lru_cache(maxsize=1)
def popularity_rank() -> dict[str, int]:
    try:
        with gzip.open(SEED, "rt", newline="") as fh:
            return {row["sku_id"]: i for i, row in enumerate(csv.DictReader(fh))}
    except OSError:
        return {}


def warm() -> None:
    """Read the ranks now, e.g. from the app's startup hook, so no request pays for it."""
    popularity_rank()


async def load_popularity() -> dict[str, int]:
    if popularity_rank.cache_info().currsize:
        return popularity_rank()
    return await asyncio.to_thread(popularity_rank)
