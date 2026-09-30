# ETL

All scripts run from `backend/` so they can import `app`:

```bash
cd backend
PYTHONPATH=. uv run python ../scripts/etl/build_catalog.py --seed-only  # load committed seed into skus
PYTHONPATH=. uv run python ../scripts/etl/build_catalog.py              # rebuild seed from data/raw, then load
PYTHONPATH=. uv run python ../scripts/etl/gen_orders.py                 # synthetic orders + inventory, then a forecast run
PYTHONPATH=. uv run python ../scripts/etl/sample_search.py              # row counts and sample searches
```

Every load is idempotent: it replaces table contents inside one transaction.

## Catalog source

- **Dataset:** "A-Z Medicine Dataset of India" (253,973 rows, originally scraped from
  1mg and published on Kaggle), taken from the public GitHub mirror
  <https://github.com/junioralive/Indian-Medicine-Dataset>, file
  `DATA/indian_medicine_data.csv`
  (<https://raw.githubusercontent.com/junioralive/Indian-Medicine-Dataset/main/DATA/indian_medicine_data.csv>,
  sha256 `c9de0182474f652b7790a85bf534d0df9bd814575fcbda7109696d0fb3bec042`).
- **License:** the mirror states the MIT License (Copyright (c) 2024 JuniorAlive). The
  underlying product data is 1mg's listing data; treat it as demo data, not a reference.
- Download it to `data/raw/` (gitignored). The trimmed result, `data/seed/skus.csv.gz`, is
  committed so the demo never needs the raw file.

```bash
mkdir -p data/raw && curl -sL -o data/raw/indian_medicine_data.csv \
  https://raw.githubusercontent.com/junioralive/Indian-Medicine-Dataset/main/DATA/indian_medicine_data.csv
```

## What `build_catalog.py` does

1. Drops discontinued rows. Parses `short_composition1/2` into `(salt, strength)` pairs
   (`app/catalog/normalize.py`): lowercase, strip parenthesised synonyms, fold spelling
   variants (amoxicillin → amoxycillin, acetaminophen → paracetamol, potassium
   clavulanate → clavulanic acid, …), normalize strengths (`500 mg` → `500mg`,
   `1gm` → `1000mg`, `5mg/5ml` kept, `NA` → none). `composition_key` is the salts
   sorted by name, joined as `name strength + name strength`.
2. Maps `pack_size_label` to a contract `form`, `pack_size` and `pack_label`. Counted
   packs keep their count (`strip of 10 tablets` → 10); measured packs (ml, gm, MDI
   doses) are one unit (`bottle of 100 ml syrup` → 1). Inhalation capsules and ampoules count units (`packet of 30 rotacaps` → 30, `packet of 5 respules` → 5) while metered-dose inhalers are one device; suppositories, patches and lozenges count units too. Unmappable packs (kits, soaps,
   plain "solution") are dropped: 244,207 of 246,068 active rows survive.
3. Cleans brand names by cutting the dosage-form tail (`Augmentin 625 Duo Tablet` →
   `Augmentin 625 Duo`) and keeps one row per brand × composition × form.
4. Trims to **9,303 SKUs**: the 1,500 most common composition keys, and for each the 5
   best-known brands plus the cheapest per form; then every brand in
   `data/must_include.txt` (228 names: the fixture brands and common Indian Rx/OTC
   brands) with its cheapest same-composition alternative. "Best-known" uses the
   dataset's own order: rows are grouped by first letter and sorted by popularity within
   a letter (row 1 is Augmentin 625 Duo; the D block opens with Dolo 650). Listings priced
   under a fifth of the median unit price for their composition are not picked as the
   cheapest, because they are almost always data errors.
5. Adds `data/manual_skus.csv`: five well-known products that the dataset lacks (Pan 40,
   Electral Powder, Shelcal 500, Limcee 500, Crocin 650). They are real products with
   **approximate** MRPs. `data/sku_id_overrides.csv` pins the ids used in
   `contracts/fixtures/` (`sku_augmentin_625`, `sku_pan_40`, …).
6. Validates every row against `app.contracts.SKU`, writes the seed, loads `skus`.

Limitation: the dataset keeps at most two salts per product, so a third ingredient (for
example lactic acid bacillus in some amox-clav brands) is not part of the key.

## Rx flag (approximate)

`data/schedule_h.csv` is a hand-curated list of about 300 salts under Schedule H, H1 or X
of the Drugs and Cosmetics Rules (antibiotics, antituberculars, PPIs, antihypertensives,
antidiabetics, statins, steroids, psychotropics, opioids, …). A salt entry also covers
its salt forms (`metoprolol` covers `metoprolol succinate`). `rx_only` is true when any
salt is listed; `schedule` is the strictest (X > H1 > H). Paracetamol, cetirizine, ORS,
antacids, vitamins and similar stay OTC. **This list is approximate and was written for a
demo; it is not a regulatory reference.** 74.6% of the trimmed catalog is Rx-only.

## Forecast data is synthetic

**Every order in `synthetic_orders` and every stock level in `inventory` is made up.**
`gen_orders.py` (logic in `backend/app/forecast/synthetic.py`) generates 90 days of hourly
demand, ending at the current hour, for 50 real catalog SKUs in three areas, with a fixed
random seed. The structure injected on purpose: an hour-of-week curve (near zero from
01:00 to 06:00, a daytime plateau, an evening peak from 18:00 to 22:00, a Saturday lift
and a Sunday bump); a different mix per area (Area A is chronic-heavy: metformin,
telmisartan, amlodipine, statins; Area B is acute and OTC: antibiotics, PPIs, paracetamol,
antihistamines; Area C is mixed); a flu-style outbreak over the last 21 days that ramps
paracetamol, ORS, cetirizine and azithromycin SKUs up to 2.6x over a week; and Poisson
noise on every hour. Inventory is 1 to 3 days of recent demand with a 24 h lead time,
except 12 series (the outbreak SKUs in Area B plus four at random) seeded at under a
day so the stockout alerts fire. Only non-zero hours are stored. The forecast model, the
backtest and the reorder rule are described in `backend/app/forecast/model.py`.
