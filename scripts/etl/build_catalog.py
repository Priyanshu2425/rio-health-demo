"""Build the Rio SKU catalog and load it into `skus`.

    cd backend && PYTHONPATH=. uv run python ../scripts/etl/build_catalog.py            # build + load
    cd backend && PYTHONPATH=. uv run python ../scripts/etl/build_catalog.py --no-load  # build seed only
    cd backend && PYTHONPATH=. uv run python ../scripts/etl/build_catalog.py --seed-only  # load committed seed

Build reads `data/raw/indian_medicine_data.csv` (see README for the source), normalizes
compositions and packs, trims to the most common compositions and writes
`data/seed/skus.csv.gz`. Load replaces the table contents in one transaction.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
import time
from collections import Counter

import pandas as pd
from common import DATA, RAW, SEED, connect

from app.catalog.normalize import (
    clean_brand,
    composition_key,
    parse_composition,
    parse_pack,
    schedule_for,
)
from app.contracts import SKU

RAW_CSV = RAW / "indian_medicine_data.csv"
SEED_CSV = SEED / "skus.csv.gz"
TOP_KEYS = 1500
EXTRA_BRANDS_PER_KEY = 4

SEED_COLUMNS = [
    "sku_id",
    "brand_name",
    "manufacturer",
    "form",
    "pack_size",
    "pack_label",
    "mrp_inr",
    "composition",
    "composition_key",
    "rx_only",
    "schedule",
]


def load_schedule_map() -> dict[str, str]:
    with open(DATA / "schedule_h.csv") as fh:
        return {row["salt"].strip().lower(): row["schedule"].strip() for row in csv.DictReader(fh)}


def load_must_include() -> list[str]:
    lines = (DATA / "must_include.txt").read_text().splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


def load_overrides() -> dict[str, str]:
    with open(DATA / "sku_id_overrides.csv") as fh:
        return {row["brand_name"].lower(): row["sku_id"] for row in csv.DictReader(fh)}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


def normalize_rows(df: pd.DataFrame, schedule_map: dict[str, str]) -> list[dict]:
    """Raw dataset rows -> normalized candidate SKUs (no ids yet). Unmappable rows are dropped."""
    rows: list[dict] = []
    for rec in df.itertuples(index=False):
        pack = parse_pack(rec.pack_size_label)
        if pack is None:
            continue
        salts = parse_composition(rec.short_composition1, rec.short_composition2)
        if not salts:
            continue
        try:
            price = float(rec.price)
        except (TypeError, ValueError):
            continue
        if not price > 0:
            continue
        schedule = schedule_for(salts, schedule_map)
        rows.append(
            {
                "brand_name": clean_brand(rec.name),
                "manufacturer": _clean_text(rec.manufacturer_name),
                "form": pack.form,
                "pack_size": pack.pack_size,
                "pack_label": pack.pack_label,
                "mrp_inr": round(price, 2),
                "composition": [s.model_dump() for s in salts],
                "composition_key": composition_key(salts),
                "rx_only": schedule is not None,
                "schedule": schedule,
                "pop_rank": int(rec.pop_rank),
            }
        )
    return rows


def manual_rows(schedule_map: dict[str, str]) -> list[dict]:
    """Well-known SKUs missing from the dataset (see README): real products, approximate MRP."""
    out = []
    with open(DATA / "manual_skus.csv") as fh:
        for rec in csv.DictReader(fh):
            pack = parse_pack(rec["pack_size_label"])
            if pack is None:
                raise SystemExit(f"manual SKU {rec['sku_id']}: cannot parse pack")
            salts = parse_composition(rec["composition"])
            schedule = schedule_for(salts, schedule_map)
            out.append(
                {
                    "sku_id": rec["sku_id"],
                    "brand_name": rec["brand_name"],
                    "manufacturer": rec["manufacturer_name"],
                    "form": pack.form,
                    "pack_size": pack.pack_size,
                    "pack_label": pack.pack_label,
                    "mrp_inr": float(rec["price"]),
                    "composition": [s.model_dump() for s in salts],
                    "composition_key": composition_key(salts),
                    "rx_only": schedule is not None,
                    "schedule": schedule,
                    "pop_rank": -1,
                }
            )
    return out


def select(rows: list[dict], must_include: list[str]) -> list[dict]:
    """Trim to the most common compositions plus must-include brands."""
    # one row per (brand, composition, form): keep the most popular listing
    rows = sorted(rows, key=lambda r: r["pop_rank"])
    seen: set[tuple] = set()
    unique: list[dict] = []
    for r in rows:
        ident = (r["brand_name"].lower(), r["composition_key"], r["form"])
        if ident not in seen:
            seen.add(ident)
            unique.append(r)

    by_key: dict[str, list[dict]] = {}
    for r in unique:
        by_key.setdefault(r["composition_key"], []).append(r)
    counts = Counter({k: len(v) for k, v in by_key.items()})

    def unit_price(r: dict) -> float:
        return r["mrp_inr"] / r["pack_size"]

    chosen: dict[int, dict] = {}

    def add(r: dict) -> None:
        chosen[id(r)] = r

    def add_cheapest(group: list[dict], form: str) -> None:
        same_form = [r for r in group if r["form"] == form]
        if len(same_form) >= 3:
            # Some listings carry implausible prices (a 625 mg amox-clav strip at ₹7).
            # Don't let one of those become "the generic": ignore anything under a
            # fifth of the median price per unit for that composition and form.
            floor = 0.2 * statistics.median(unit_price(r) for r in same_form)
            same_form = [r for r in same_form if unit_price(r) >= floor]
        if same_form:
            add(min(same_form, key=lambda r: (unit_price(r), r["pop_rank"])))

    for key, _ in counts.most_common(TOP_KEYS):
        group = by_key[key]  # already in popularity order
        popular = group[: EXTRA_BRANDS_PER_KEY + 1]
        for r in popular:
            add(r)
        for form in {r["form"] for r in popular}:
            add_cheapest(group, form)

    wanted = {b.lower() for b in must_include}
    for r in unique:
        if r["brand_name"].lower() in wanted:
            add(r)
            add_cheapest(by_key[r["composition_key"]], r["form"])

    return sorted(chosen.values(), key=lambda r: (r["pop_rank"], r["brand_name"].lower()))


def assign_ids(rows: list[dict], overrides: dict[str, str]) -> None:
    used = {r["sku_id"] for r in rows if r.get("sku_id")}
    for r in rows:
        if r.get("sku_id"):
            continue
        override = overrides.get(r["brand_name"].lower())
        if override and override not in used:
            r["sku_id"] = override
            used.add(override)
            continue
        base = "sku_" + _slug(r["brand_name"])
        candidates = [base, f"{base}_{r['form']}", f"{base}_{r['form']}_{r['pack_size']}"]
        sku_id = next((c for c in candidates if c not in used), None)
        n = 2
        while sku_id is None:
            if f"{base}_{n}" not in used:
                sku_id = f"{base}_{n}"
            n += 1
        r["sku_id"] = sku_id
        used.add(sku_id)


def build() -> pd.DataFrame:
    if not RAW_CSV.exists():
        raise SystemExit(f"{RAW_CSV} is missing; see scripts/etl/README.md for the download")
    started = time.perf_counter()
    df = pd.read_csv(RAW_CSV)
    df = df.rename(columns={"price(₹)": "price"})
    # The dataset is grouped by first letter and, within a letter, ordered by popularity
    # (row 1 is Augmentin 625 Duo, the D block starts with Dolo 650). Keep that as a rank.
    df["pop_rank"] = df.groupby(df["name"].str[0].str.upper()).cumcount()
    df = df[~df["Is_discontinued"].astype(str).str.upper().eq("TRUE")]

    schedule_map = load_schedule_map()
    rows = normalize_rows(df, schedule_map)
    print(f"raw rows: {len(df):,} active; normalized: {len(rows):,}")

    must = load_must_include()
    manual = manual_rows(schedule_map)
    selected = select(rows, must)
    manual_keys = {(m["brand_name"].lower(), m["composition_key"], m["form"]) for m in manual}
    selected = [
        r for r in selected if (r["brand_name"].lower(), r["composition_key"], r["form"]) not in manual_keys
    ]
    selected = manual + selected
    assign_ids(selected, load_overrides())

    have = {r["brand_name"].lower() for r in selected}
    missing = [b for b in must if b.lower() not in have]
    if missing:
        print(f"must-include brands not found ({len(missing)}): {', '.join(missing)}")

    for r in selected:  # validate against the contract before writing anything
        SKU.model_validate({k: r[k] for k in SEED_COLUMNS})

    out = pd.DataFrame(selected)[SEED_COLUMNS]
    out["composition"] = out["composition"].map(lambda c: json.dumps(c, separators=(",", ":")))
    SEED.mkdir(parents=True, exist_ok=True)
    out.to_csv(SEED_CSV, index=False, compression={"method": "gzip", "mtime": 0})
    rx_share = out["rx_only"].mean()
    print(
        f"selected {len(out):,} SKUs, {out['composition_key'].nunique():,} compositions, "
        f"rx_only {rx_share:.1%}; wrote {SEED_CSV.relative_to(DATA.parent)} "
        f"in {time.perf_counter() - started:.1f}s"
    )
    return out


def read_seed() -> pd.DataFrame:
    return pd.read_csv(SEED_CSV, keep_default_na=False, dtype={"schedule": str})


def load(seed: pd.DataFrame) -> None:
    """Replace `skus` with the seed in one transaction.

    Rows are upserted and stale ids deleted, so forecast tables that reference stable ids
    survive a catalog rebuild; forecast rows for ids that disappear are deleted first.
    """
    records = []
    for r in seed.to_dict("records"):
        schedule = r["schedule"] or None
        records.append(
            (
                r["sku_id"],
                r["brand_name"],
                r["manufacturer"],
                r["form"],
                int(r["pack_size"]),
                r["pack_label"],
                float(r["mrp_inr"]),
                r["composition"] if isinstance(r["composition"], str) else json.dumps(r["composition"]),
                r["composition_key"],
                str(r["rx_only"]).lower() == "true",
                schedule,
            )
        )
    with connect() as conn, conn.transaction():
        conn.execute("CREATE TEMP TABLE skus_new (LIKE skus INCLUDING DEFAULTS) ON COMMIT DROP")
        with conn.cursor().copy(
            "COPY skus_new (sku_id, brand_name, manufacturer, form, pack_size, pack_label, mrp_inr, "
            "composition, composition_key, rx_only, schedule) FROM STDIN"
        ) as copy:
            for rec in records:
                copy.write_row(rec)
        conn.execute("DELETE FROM synthetic_orders WHERE sku_id NOT IN (SELECT sku_id FROM skus_new)")
        conn.execute("DELETE FROM inventory WHERE sku_id NOT IN (SELECT sku_id FROM skus_new)")
        conn.execute("DELETE FROM skus WHERE sku_id NOT IN (SELECT sku_id FROM skus_new)")
        conn.execute(
            """
            INSERT INTO skus SELECT * FROM skus_new
            ON CONFLICT (sku_id) DO UPDATE SET
                brand_name = EXCLUDED.brand_name, manufacturer = EXCLUDED.manufacturer,
                form = EXCLUDED.form, pack_size = EXCLUDED.pack_size,
                pack_label = EXCLUDED.pack_label, mrp_inr = EXCLUDED.mrp_inr,
                composition = EXCLUDED.composition, composition_key = EXCLUDED.composition_key,
                rx_only = EXCLUDED.rx_only, schedule = EXCLUDED.schedule
            """
        )
        count = conn.execute("SELECT count(*), avg(rx_only::int) FROM skus").fetchone()
    print(f"loaded skus: {count[0]:,} rows, rx_only {float(count[1]):.1%}")


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--no-load", action="store_true", help="build the seed, skip the database")
    group.add_argument("--seed-only", action="store_true", help="load the committed seed, skip the build")
    args = parser.parse_args(argv)
    if not args.seed_only:
        build()
    if not args.no_load:
        load(read_seed())


if __name__ == "__main__":
    main(sys.argv[1:])
