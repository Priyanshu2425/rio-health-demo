"""Synthetic hourly pharmacy demand. All of it is made up; see scripts/etl/README.md.

Pure (numpy + pandas, no database), seeded, so the output is reproducible for a given
end time. `scripts/etl/gen_orders.py` writes it to `synthetic_orders` and `inventory`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

IST = ZoneInfo("Asia/Kolkata")
AREAS = ["Area A", "Area B", "Area C"]
LEAD_TIME_HOURS = 24
SEED = 20260930

Category = Literal["chronic", "acute", "otc"]

# (sku_id, category). Ids come from data/seed/skus.csv.gz.
PLAN: list[tuple[str, Category]] = [
    # chronic: diabetes, hypertension, lipids, thyroid
    ("sku_glycomet_500_sr", "chronic"),
    ("sku_telma_40", "chronic"),
    ("sku_amlong", "chronic"),
    ("sku_ecosprin_75", "chronic"),
    ("sku_rozavel_10", "chronic"),
    ("sku_thyronorm_50mcg", "chronic"),
    ("sku_met_xl_50", "chronic"),
    ("sku_janumet_50mg_500mg", "chronic"),
    ("sku_amaryl_1mg", "chronic"),
    ("sku_galvus_met_50mg_500mg", "chronic"),
    ("sku_losar_50", "chronic"),
    ("sku_cilacar_10", "chronic"),
    ("sku_clopitab", "chronic"),
    ("sku_storvas_10", "chronic"),
    ("sku_glimisave_m_1", "chronic"),
    ("sku_istamet_50mg_500mg", "chronic"),
    ("sku_rosuvas_10", "chronic"),
    ("sku_concor_5", "chronic"),
    ("sku_telma_am", "chronic"),
    ("sku_shelcal_500", "chronic"),
    # acute prescriptions: antibiotics, PPIs, antiemetics
    ("sku_azithral_500", "acute"),
    ("sku_azee_500", "acute"),
    ("sku_augmentin_625", "acute"),
    ("sku_moxclav_625", "acute"),
    ("sku_pan_40", "acute"),
    ("sku_pan_d", "acute"),
    ("sku_omez", "acute"),
    ("sku_razo_20", "acute"),
    ("sku_rantac_150", "acute"),
    ("sku_montair_lc", "acute"),
    ("sku_ondem_4", "acute"),
    ("sku_taxim_o_200", "acute"),
    ("sku_zifi_200", "acute"),
    ("sku_oflox_200", "acute"),
    ("sku_ciplox_500", "acute"),
    ("sku_metrogyl_400", "acute"),
    ("sku_zerodol_sp", "acute"),
    # OTC and near-OTC
    ("sku_dolo_650", "otc"),
    ("sku_crocin_650", "otc"),
    ("sku_calpol_500mg", "otc"),
    ("sku_electral_21g", "otc"),
    ("sku_cetzine", "otc"),
    ("sku_okacet", "otc"),
    ("sku_allegra_120mg", "otc"),
    ("sku_levocet", "otc"),
    ("sku_ascoril_ls", "otc"),
    ("sku_combiflam", "otc"),
    ("sku_meftal_spas", "otc"),
    ("sku_cyclopam", "otc"),
    ("sku_limcee_500", "otc"),
]

# Flu-style outbreak over the last SPIKE_DAYS: paracetamol, ORS, cetirizine, azithromycin.
SPIKE_SKUS = {
    "sku_dolo_650",
    "sku_crocin_650",
    "sku_calpol_500mg",
    "sku_electral_21g",
    "sku_cetzine",
    "sku_okacet",
    "sku_azithral_500",
    "sku_azee_500",
}
SPIKE_DAYS = 21
SPIKE_PEAK = 2.6  # demand multiplier once the outbreak has built up
SPIKE_RAMP_DAYS = 7

# Base packs per day in a neutral area, drawn per SKU from these ranges.
BASE_DAILY: dict[Category, tuple[float, float]] = {
    "chronic": (12, 30),
    "acute": (8, 20),
    "otc": (20, 50),
}

# Area mix: A is chronic-heavy (older residential), B acute/OTC (students, offices), C mixed.
AREA_MIX: dict[str, dict[Category, float]] = {
    "Area A": {"chronic": 1.8, "acute": 0.6, "otc": 0.7},
    "Area B": {"chronic": 0.5, "acute": 1.6, "otc": 1.6},
    "Area C": {"chronic": 1.0, "acute": 1.0, "otc": 1.0},
}

# Hour of day (IST): near zero 01-06, a daytime plateau, an evening peak 18-22.
HOUR_WEIGHTS = np.array(
    [0.25, 0.05, 0.03, 0.02, 0.02, 0.03, 0.08, 0.35, 0.7, 0.9, 1.0, 1.0,
     0.95, 0.85, 0.8, 0.8, 0.9, 1.1, 1.6, 1.9, 2.0, 1.8, 1.3, 0.6]
)  # fmt: skip
# Day of week, Monday first: a Saturday lift and a Sunday bump.
DOW_WEIGHTS = np.array([1.0, 0.95, 0.95, 1.0, 1.05, 1.1, 1.3])


def hour_of_week_curve() -> np.ndarray:
    """168 hourly shares, Monday 00:00 first; any 7 consecutive days sum to 7."""
    curve = np.outer(DOW_WEIGHTS, HOUR_WEIGHTS).ravel()
    return curve / curve.sum() * 7


def end_of_history(now: datetime | None = None) -> datetime:
    """Start of the current hour in IST: history covers the hours before it."""
    now = (now or datetime.now(IST)).astimezone(IST)
    return now.replace(minute=0, second=0, microsecond=0)


@dataclass
class SyntheticData:
    hours: pd.DatetimeIndex  # hourly, IST, oldest first
    demand: pd.DataFrame  # index hours, columns MultiIndex (area, sku_id), packs per hour
    inventory: pd.DataFrame  # area, sku_id, on_hand, lead_time_hours
    low_stock: set[tuple[str, str]]  # (area, sku_id) seeded deliberately low


def generate(end: datetime, days: int = 90, seed: int = SEED) -> SyntheticData:
    rng = np.random.default_rng(seed)
    end = end_of_history(end)
    hours = pd.date_range(end - timedelta(days=days), end - timedelta(hours=1), freq="h", tz=IST)
    how = (hours.dayofweek * 24 + hours.hour).to_numpy()
    shape = hour_of_week_curve()[how]  # expected share of one day's demand in each hour

    age_days = (end - hours.to_pydatetime()).astype("timedelta64[s]").astype(float) / 86400
    into_spike = np.clip(SPIKE_DAYS - age_days, 0, None)
    spike = np.where(
        age_days <= SPIKE_DAYS, 1 + (SPIKE_PEAK - 1) * np.minimum(1, into_spike / SPIKE_RAMP_DAYS), 1.0
    )

    base = {sku: rng.uniform(*BASE_DAILY[cat]) for sku, cat in PLAN}
    columns, series = [], []
    for area in AREAS:
        for sku, cat in PLAN:
            rate = base[sku] * AREA_MIX[area][cat] * shape
            if sku in SPIKE_SKUS:
                rate = rate * spike
            columns.append((area, sku))
            series.append(rng.poisson(rate))
    demand = pd.DataFrame(
        np.column_stack(series),
        index=hours,
        columns=pd.MultiIndex.from_tuples(columns, names=["area", "sku_id"]),
    )

    # On hand: 1-3 days of recent demand. Spike SKUs in the acute-heavy Area B, and a few
    # others picked at random, get well under a day so the stockout alerts fire.
    recent = demand.iloc[-7 * 24 :].sum() / 7
    low = {("Area B", sku) for sku in SPIKE_SKUS}
    others = [c for c in columns if c not in low]
    for i in rng.choice(len(others), size=4, replace=False):
        low.add(others[i])
    rows = []
    for area, sku in columns:
        days_cover = rng.uniform(0.2, 0.6) if (area, sku) in low else rng.uniform(1.0, 3.0)
        rows.append(
            {
                "area": area,
                "sku_id": sku,
                "on_hand": round(float(recent[(area, sku)]) * days_cover),
                "lead_time_hours": LEAD_TIME_HOURS,
            }
        )
    return SyntheticData(hours=hours, demand=demand, inventory=pd.DataFrame(rows), low_stock=low)
