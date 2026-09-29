# 01: Data + Forecast (`feat/data-forecast`)

Read first: `docs/DECISIONS.md`, `contracts/README.md`, `backend/app/contracts.py`,
`backend/migrations/001_init.sql`.

## You own

`backend/app/catalog/`, `backend/app/forecast/`, `scripts/etl/`, `data/`,
`backend/tests/catalog/`, `backend/tests/forecast/`, `docs/verify/feat-data-forecast.md`.
Touch nothing else. If you need a contract, schema or dependency change, stop and report
it.

## Part A: Catalog (do this first; the parser agent depends on it)

1. **ETL** (`scripts/etl/build_catalog.py`, run with `cd backend && PYTHONPATH=. uv run python ../scripts/etl/build_catalog.py`):
   read the Kaggle CSV from `data/raw/`, then:
   - Parse composition strings such as `"Amoxycillin (500mg) + Clavulanic Acid (125mg)"`
     into `Salt` lists. Lowercase, normalize units (`500 mg` → `500mg`, `5mg/5ml` kept),
     and fold spelling variants with a small alias map (amoxicillin → amoxycillin,
     paracetamol ← acetaminophen, …).
   - Build `composition_key`: salts sorted by name, joined `"name strength + name strength"`.
   - Map pack descriptions to `form`, `pack_size` and `pack_label`. Drop rows you can't map.
   - **Trim to 5–10k SKUs:** the ~1,500 most common composition keys, and for each keep the
     cheapest plus up to 5 more well-known brands. Always include the brands used in
     `contracts/fixtures/` and the common Indian brands a prescription would name (make a
     `data/must_include.txt` of about 150).
   - Write `data/seed/skus.csv.gz` (committed, so the demo never depends on Kaggle) and
     load it into `skus`.
2. **Rx flag** (`data/schedule_h.csv`): hand-curate about 150 Schedule H/H1/X salts
   (antibiotics, PPIs, antihypertensives, antidiabetics, statins, steroids, psychotropics,
   and so on) with their schedule. `rx_only = any salt is scheduled`; `schedule` = the
   strictest one. Paracetamol, ORS, cetirizine, antacids, vitamins and similar stay OTC.
3. **`app/catalog/__init__.py`:** implement `search`, `get_sku` and `cheapest_generic`.
   Search uses `pg_trgm` `similarity()` / `word_similarity()` on `lower(brand_name)` and
   `composition_key`, takes the better of the two, and returns scores in 0..1. Target
   < 50 ms per query.
4. **Tests** (`backend/tests/catalog/`, marked `db`): "augmentin 625" → an amoxycillin
   500 + clav 125 SKU in the top 1; "amoxicillin clavulanic 500 125" → the same
   composition in the top 3; "pan 40" → pantoprazole 40mg; a generic lookup returns
   something cheaper with the same key; OTC/Rx flags are right for 10 known salts. Also
   unit tests with no database for the composition parser.

## Part B: Forecast (after A is merged or verified)

1. **Generator** (`scripts/etl/gen_orders.py`, run the same way): 90 days of hourly orders, ending now,
   for about 50 SKUs × `Area A`, `Area B`, `Area C`. Include:
   - An hour-of-week curve (evening peak 18–22, Sunday bump, near zero from 01–06)
   - A different mix per area (A: chronic, e.g. metformin/amlodipine/telmisartan; B:
     acute and OTC; C: mixed)
   - A flu-style spike in the last 21 days for paracetamol, ORS, cetirizine and
     azithromycin
   - Poisson noise

   Write to `synthetic_orders`, and seed `inventory` with on-hand stock of about 1–3
   days of demand and a 24 h lead time. Make some SKUs deliberately low so that alerts
   fire. The seed is fixed, so the output is reproducible.
2. **Model** (`app/forecast/`): forecast = hour-of-week profile (mean of the last 8
   weeks at that hour) × level (7-day EWMA of daily totals ÷ the profile's daily total).
   Backtest the last 14 days against naive "same hour last week" and report MAPE on
   daily totals, so the zeros don't blow it up.
3. **Reorder:** `forecast_over_lead_time` = the sum of the next 24 h.
   `reorder_qty = max(0, ceil(forecast_over_lead_time × 1.2 − on_hand))`, where the 1.2
   is a stated buffer. `stockout_risk` = on-hand runs out within the lead time, and
   `hours_to_stockout` comes from the cumulative forecast.
4. `run()` stores a `forecast_runs` row plus one `forecast_series` row per SKU × area, with
   the last 7 days of actuals and the next 48 h of forecast. `get_summary` and
   `get_sku_forecast` read the latest run.
5. **Tests:** the backtest beats naive on the spike SKUs; `reorder_qty` is ≥ 0; at least one
   `stockout_risk`; outputs validate against the contracts.
6. `scripts/etl/README.md`: one paragraph stating plainly that the data is synthetic and
   what structure was injected.

## Done means

- `uv run pytest -q` is green (db tests run against your `.env`).
- `docs/verify/feat-data-forecast.md` has the exact commands and expected output: row
  counts, 3 sample searches with their results, and the backtest numbers.
- Push the branch and open a PR with `gh pr create --base main`. The PR body summarizes
  the numbers.

Timebox: Part A, 2 h. Part B, 1.5 h. If you're over, ship A and report.
