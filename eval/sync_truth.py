"""Check truth composition keys against the loaded catalog (read-only).

    cd backend && uv run python ../eval/sync_truth.py          # report only
    cd backend && uv run python ../eval/sync_truth.py --write  # rewrite truth keys

For every truth line it finds catalog SKUs whose brand name starts with the first word
of the truth brand and checks that one of them has the truth composition_key (after
normalization). With --write, a truth key is replaced by the catalog's key when
all matching SKUs agree on one. Only the truth JSON files are written; the database is
opened read-only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL_DIR.parent / "backend"))

import catalog_adapter
import metrics
from psycopg.rows import dict_row

from app.core.config import get_settings

LOOKUP = """
SELECT DISTINCT composition_key FROM skus
WHERE lower(brand_name) LIKE lower(%(prefix)s) || '%%'
"""


async def main_async(write: bool) -> int:
    s = get_settings()
    if not s.database_url:
        print("RIO_HEALTH_DATABASE_URL is not set", file=sys.stderr)
        return 2
    conn = await catalog_adapter.connect_read_only(s.database_url, s.db_schema)
    try:
        if await catalog_adapter.sku_count(conn) == 0:
            print("skus table is empty; load the catalog first", file=sys.stderr)
            return 1
        cache: dict[str, list[str]] = {}
        missing, differ, changed = 0, 0, 0
        files = sorted((EVAL_DIR / "synth").glob("*.truth.json")) + sorted(
            (EVAL_DIR / "handwritten").glob("*.truth.json")
        )
        for path in files:
            truth = json.loads(path.read_text())
            dirty = False
            for line in truth["lines"]:
                prefix = re.split(r"[\s-]+", line["drug"].strip())[0]
                if prefix not in cache:
                    async with conn.cursor(row_factory=dict_row) as cur:
                        await cur.execute(LOOKUP, {"prefix": prefix})
                        cache[prefix] = [r["composition_key"] for r in await cur.fetchall()]
                keys = cache[prefix]
                want = metrics.norm_key(line["composition_key"])
                if not keys:
                    missing += 1
                    print(f"{path.name}: '{prefix}' not in catalog")
                elif want not in {metrics.norm_key(k) for k in keys}:
                    differ += 1
                    print(f"{path.name}: '{prefix}' truth={line['composition_key']!r} catalog={keys[:3]}")
                    if write and len({metrics.norm_key(k) for k in keys}) == 1:
                        line["composition_key"] = keys[0]
                        dirty = True
                        changed += 1
            if dirty:
                path.write_text(json.dumps(truth, indent=2) + "\n")
        print(f"missing brands: {missing}, key differs: {differ}, rewritten: {changed}")
        return 0
    finally:
        await conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true")
    sys.exit(asyncio.run(main_async(ap.parse_args().write)))


if __name__ == "__main__":
    main()
