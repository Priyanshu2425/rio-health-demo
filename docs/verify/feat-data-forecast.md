# Verify: feat/data-forecast

Catalog (Part A) and synthetic demand forecast (Part B). Every command runs from the repo
root with the shared `.env` linked (`RIO_HEALTH_DATABASE_URL`, schema `app_rio_health`).
Numbers below are from the run on 2026-09-30 at 14:00 IST.

## 1. Load the catalog

From the committed seed (no raw download needed):

```bash
cd backend && PYTHONPATH=. uv run python ../scripts/etl/build_catalog.py --seed-only
```

```
loaded skus: 9,303 rows, rx_only 74.6%
```

To rebuild the seed from the raw dataset (download command in `scripts/etl/README.md`):

```bash
cd backend && PYTHONPATH=. uv run python ../scripts/etl/build_catalog.py
```

```
raw rows: 246,068 active; normalized: 244,207
selected 9,303 SKUs, 1,541 compositions, rx_only 74.6%; wrote data/seed/skus.csv.gz in ~15s
loaded skus: 9,303 rows, rx_only 74.6%
```

The load is idempotent: running it twice leaves the same 9,303 rows.

## 2. Sample searches

```bash
cd backend && PYTHONPATH=. uv run python ../scripts/etl/sample_search.py \
  "augmentin 625" "amoxicillin clavulanate 500/125" "pan 40"
```

```
skus: 9303 rows, 1541 composition keys, rx_only 74.6%

search 'augmentin 625'
  0.89  sku_augmentin_625        Augmentin 625 Duo    amoxycillin 500mg + clavulanic acid 125mg  ₹223.42 Rx H
  0.63  sku_augmentin_duo        Augmentin Duo        amoxycillin 200mg + clavulanic acid 28.5mg  ₹67.2 Rx H
  0.63  sku_augmentin_dds        Augmentin DDS        amoxycillin 400mg/5ml + clavulanic acid 57mg/5ml  ₹173.0 Rx H
  generic for top hit: Ozimentin LB 500mg/125mg ₹35.0 / strip of 6 tablets

search 'amoxicillin clavulanate 500/125'
  0.85  sku_augmentin_625        Augmentin 625 Duo    amoxycillin 500mg + clavulanic acid 125mg  ₹223.42 Rx H
  0.85  sku_clavam_625           Clavam 625           amoxycillin 500mg + clavulanic acid 125mg  ₹223.32 Rx H
  0.85  sku_moxikind_cv_625      Moxikind-CV 625      amoxycillin 500mg + clavulanic acid 125mg  ₹171.1 Rx H
  generic for top hit: Ozimentin LB 500mg/125mg ₹35.0 / strip of 6 tablets

search 'pan 40'
  1.00  sku_pan_40               Pan 40               pantoprazole 40mg  ₹155.0 Rx H
  0.55  sku_pantop_40            Pantop 40            pantoprazole 40mg  ₹155.0 Rx H
  0.51  sku_pan_d                Pan-D                domperidone 30mg + pantoprazole 40mg  ₹199.0 Rx H
  generic for top hit: Pantakind ₹63.76 / strip of 15 tablets
```

Typos work too: `augmantin` returns the Augmentin family (score 0.48). Wall-clock time per
search is 85 to 150 ms from a laptop, which is almost all network round trip to Neon
(`SELECT 1` alone takes about 80 ms). Server-side `EXPLAIN ANALYZE` execution time: brand
queries about 1 ms, `amoxycillin clavulanic acid 500 125` 5 ms, `paracetamol 650` (400+
candidate SKUs) about 41 ms. Search uses pg_trgm's default thresholds and never changes a
connection setting (`SHOW pg_trgm.word_similarity_threshold` stays `0.6`).

Generic suggestions (`cheapest_generic`) compare price per unit within the same
composition and form, skip listings under a fifth of that group's median unit price
(data errors), and for one-unit packs (bottles, tubes, sachets, inhalers) only offer the
same volume. Examples: `Oflox 200` (₹88.57 / 10) → Zenflox 200 ₹69.90 / 10, where it
used to offer Oflocin at ₹1.14 a tablet against a ₹7.98 median; `Dolo` drops (15 ml,
₹30.07) → Babygesic 15 ml ₹22.09; `Dolo 250` (60 ml) only considers 60 ml bottles.

Search breaks score ties in SQL with `skus.popularity_rank` (written by the catalog load
from the seed's row order), then price per unit. The running app reads only the
database; no code under `backend/app` opens the seed or any other data file.

## 3. Synthetic orders, inventory and a forecast run

```bash
cd backend && PYTHONPATH=. uv run python ../scripts/etl/gen_orders.py
```

```
synthetic_orders: 156,194 non-zero hourly rows (343,781 packs), 50 SKUs x 3 areas, 2026-07-02 14:00 to 2026-09-30 13:00 IST
inventory: 150 rows, 12 seeded low
forecast run: backtest 14 days, model MAPE 22.9% vs naive 28.5%; 14 stockout risks of 150 (~17s)
  Area C Telma 40: on hand 4, next 24h 17.06, out in 3.9 h, reorder 17
  Area A Ascoril LS: on hand 11, next 24h 27.8, out in 5.9 h, reorder 23
  Area B Azithral 500: on hand 25, next 24h 61.29, out in 6.6 h, reorder 49
  Area B Dolo 650: on hand 50, next 24h 108.63, out in 6.8 h, reorder 81
  Area B Razo 20: on hand 12, next 24h 25.87, out in 7.2 h, reorder 20
```

Timestamps depend on when you run it; the counts do not (fixed seed).

Backtest (last 14 days, one-day-ahead from each midnight, MAPE on daily totals):

| Series | Model | Naive (same hour last week) |
|---|---|---|
| All 150 SKU x area series | **22.9%** | 28.5% |
| 24 outbreak series (paracetamol, ORS, cetirizine, azithromycin) | **18.4%** | 23.5% |

The model beats naive on 134 of 150 series.

Row counts after both scripts: `skus` 9,303; `synthetic_orders` 156,194; `inventory` 150;
`forecast_runs` at most 5 (older runs are pruned); `forecast_series` 150 per run.

`app.forecast.run(conn)` **commits the connection it is given** (the new run has to be
visible to other connections) and **prunes `forecast_runs` to the latest 5 runs**, whose
`forecast_series` rows cascade.

## 4. Checks

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest -q
```

```
All checks passed!
All files formatted
120 passed
```

Catalog tests (`tests/catalog/`): pure parser and pack tests (including rotacap, respule and MDI packs and
pack-volume comparison); DB tests for `augmentin 625` top 1, the amox-clav composition in
the top 3, `pan 40` → pantoprazole 40mg, a cheaper generic with the same key and form,
the generic price floor (Oflox 200), same-volume generics for bottles, search leaving
the trigram threshold at its default, a typo query, fixture ids resolving, and Rx/OTC
flags for 10 salts; `popularity_rank` loaded for every SKU and used for ties. A pure guard
test keeps look-alike salts (cefixime/cefepime, quinine/quinidine, …) from being folded.
Forecast tests (`tests/forecast/`): generator structure and reproducibility, the model
recovering a known seasonal pattern, backtest beating naive (overall and on the outbreak
SKUs), reorder rule cases, `reorder_qty >= 0`, at least one stockout risk, contract
validation, and one DB test that runs, stores and reads back a forecast.
