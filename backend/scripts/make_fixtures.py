"""Write contracts/fixtures/*.json: the mock payloads frontend and backend build against.

    uv run python -m scripts.make_fixtures

Built through the Pydantic models, so a fixture that does not match the contract cannot
be written. Prices and brands are illustrative.
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.contracts import (
    SKU,
    BacktestSummary,
    CartItem,
    Confidence,
    ForecastPoint,
    ForecastSummary,
    MatchCandidate,
    Order,
    ParsedLine,
    ParsedRx,
    QueueItem,
    ReorderSuggestion,
    Salt,
    Sample,
    SkuForecast,
    SkuRef,
)

OUT = Path(__file__).resolve().parents[2] / "contracts" / "fixtures"
IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 9, 29, 18, 30, tzinfo=IST)

AUGMENTIN = SKU(
    sku_id="sku_augmentin_625",
    brand_name="Augmentin 625 Duo",
    manufacturer="GlaxoSmithKline",
    form="tablet",
    pack_size=10,
    pack_label="strip of 10 tablets",
    mrp_inr=223.5,
    composition=[Salt(name="amoxycillin", strength="500mg"), Salt(name="clavulanic acid", strength="125mg")],
    composition_key="amoxycillin 500mg + clavulanic acid 125mg",
    rx_only=True,
    schedule="H",
)
MOXCLAV = SKU(
    sku_id="sku_moxclav_625",
    brand_name="Moxclav 625",
    manufacturer="Sun Pharma",
    form="tablet",
    pack_size=10,
    pack_label="strip of 10 tablets",
    mrp_inr=181.0,
    composition=AUGMENTIN.composition,
    composition_key=AUGMENTIN.composition_key,
    rx_only=True,
    schedule="H",
)
PAN40 = SKU(
    sku_id="sku_pan_40",
    brand_name="Pan 40",
    manufacturer="Alkem",
    form="tablet",
    pack_size=15,
    pack_label="strip of 15 tablets",
    mrp_inr=155.0,
    composition=[Salt(name="pantoprazole", strength="40mg")],
    composition_key="pantoprazole 40mg",
    rx_only=True,
    schedule="H",
)
DOLO650 = SKU(
    sku_id="sku_dolo_650",
    brand_name="Dolo 650",
    manufacturer="Micro Labs",
    form="tablet",
    pack_size=15,
    pack_label="strip of 15 tablets",
    mrp_inr=33.6,
    composition=[Salt(name="paracetamol", strength="650mg")],
    composition_key="paracetamol 650mg",
    rx_only=False,
)
ORS = SKU(
    sku_id="sku_electral_21g",
    brand_name="Electral Powder",
    manufacturer="FDC",
    form="sachet",
    pack_size=1,
    pack_label="sachet of 21.8 g",
    mrp_inr=22.0,
    composition=[Salt(name="oral rehydration salts", strength=None)],
    composition_key="oral rehydration salts",
    rx_only=False,
)

LINES = [
    ParsedLine(
        line_no=1,
        raw_text="Tab. Augmentin 625  1-0-1 x 5 days",
        drug="Augmentin",
        strength="625",
        form="tablet",
        frequency="1-0-1",
        doses_per_day=2,
        duration_days=5,
    ),
    ParsedLine(
        line_no=2,
        raw_text="Tab Pan 40  1-0-0 before food x 5d",
        drug="Pan",
        strength="40",
        form="tablet",
        frequency="1-0-0",
        doses_per_day=1,
        duration_days=None,
        illegible_fields=["duration"],
    ),
    ParsedLine(
        line_no=3,
        raw_text="Tab D?lo 650 SOS",
        drug="Dolo",
        strength="650",
        form="tablet",
        frequency="SOS",
        doses_per_day=None,
        duration_days=None,
        illegible_fields=["drug"],
    ),
]
PARSED = ParsedRx(
    doctor_name="Dr. A. Mehta",
    clinic_name="Sunrise Clinic",
    patient_name="R. Sharma",
    rx_date=date(2026, 9, 28),
    lines=LINES,
    model="example/vision-model",
    latency_ms=6120,
    cost_usd=0.0021,
)


def item(item_id, line, sku, packs, conf, generic=None):
    total = round(sku.mrp_inr * packs, 2)
    savings = round((sku.mrp_inr - generic.mrp_inr) * packs, 2) if generic else None
    return CartItem(
        item_id=item_id,
        parsed=line,
        sku=sku,
        quantity_packs=packs,
        unit_price_inr=sku.mrp_inr,
        line_total_inr=total,
        generic_alternative=generic,
        savings_inr=savings,
        confidence=conf,
    )


ITEMS = [
    item(
        "itm_1",
        LINES[0],
        AUGMENTIN,
        1,
        Confidence(score=0.94, match_score=0.97, completeness=1.0, legibility=1.0, triage="green"),
        MOXCLAV,
    ),
    item(
        "itm_2",
        LINES[1],
        PAN40,
        1,
        Confidence(
            score=0.72,
            match_score=0.9,
            completeness=0.75,
            legibility=0.8,
            triage="amber",
            reasons=["duration unreadable; assumed 1 strip"],
        ),
    ),
    item(
        "itm_3",
        LINES[2],
        DOLO650,
        1,
        Confidence(
            score=0.48,
            match_score=0.62,
            completeness=0.5,
            legibility=0.6,
            triage="red",
            reasons=["drug name unclear", "no duration (SOS)"],
        ),
    ),
]

PENDING = Order(
    order_id="ord_demo_pending",
    created_at=NOW,
    source="prescription",
    status="pending_review",
    has_image=True,
    parsed_rx=PARSED,
    items=ITEMS,
    total_inr=round(sum(i.line_total_inr for i in ITEMS), 2),
    requires_review=True,
)
VERIFIED = PENDING.model_copy(
    update={
        "order_id": "ord_demo_verified",
        "status": "verified",
        "reviewed_at": NOW + timedelta(minutes=3),
        "pharmacist_note": "Confirmed Dolo 650 with the doctor's usual pattern.",
        "items": [i.model_copy(update={"status": "approved"}) for i in ITEMS],
    }
)
TEXT_OTC_ITEMS = [
    CartItem(
        item_id="itm_t1",
        requested_text="dolo",
        sku=DOLO650,
        quantity_packs=1,
        unit_price_inr=33.6,
        line_total_inr=33.6,
        confidence=Confidence(score=0.95, match_score=0.95, completeness=1.0, legibility=1.0, triage="green"),
        status="approved",
    ),
    CartItem(
        item_id="itm_t2",
        requested_text="ORS",
        sku=ORS,
        quantity_packs=1,
        unit_price_inr=22.0,
        line_total_inr=22.0,
        confidence=Confidence(score=0.9, match_score=0.9, completeness=1.0, legibility=1.0, triage="green"),
        status="approved",
    ),
]
TEXT_OTC = Order(
    order_id="ord_demo_text_otc",
    created_at=NOW,
    source="text",
    status="confirmed_otc",
    has_image=False,
    items=TEXT_OTC_ITEMS,
    total_inr=55.6,
    requires_review=False,
)
QUEUE = [
    QueueItem(
        order_id=PENDING.order_id,
        created_at=NOW,
        source="prescription",
        item_count=3,
        counts={"green": 1, "amber": 1, "red": 1},
        worst_triage="red",
        total_inr=PENDING.total_inr,
    )
]
SEARCH = [MatchCandidate(sku=AUGMENTIN, score=0.97), MatchCandidate(sku=MOXCLAV, score=0.81)]
SAMPLES = [
    Sample(
        sample_id="typed_clinic_3",
        label="Typed clinic Rx, 3 lines",
        thumbnail_url="/api/samples/typed_clinic_3/image",
    ),
    Sample(
        sample_id="handwritten_2",
        label="Handwritten Rx, 2 lines",
        thumbnail_url="/api/samples/handwritten_2/image",
    ),
]

start = NOW.replace(minute=0) - timedelta(days=3)
POINTS = []
for h in range(24 * 5):
    ts = start + timedelta(hours=h)
    base = 2.0 + 3.0 * (18 <= ts.hour <= 21)
    POINTS.append(
        ForecastPoint(ts=ts, forecast=round(base, 2), actual=round(base * 1.1, 2) if ts < NOW else None)
    )
SKU_FORECAST = SkuForecast(
    sku_id=DOLO650.sku_id,
    brand_name=DOLO650.brand_name,
    area="Area A",
    points=POINTS,
    model_mape=0.18,
    naive_mape=0.31,
)
SUMMARY = ForecastSummary(
    generated_at=NOW,
    areas=["Area A", "Area B", "Area C"],
    skus=[SkuRef(sku_id=s.sku_id, brand_name=s.brand_name) for s in (DOLO650, ORS, PAN40)],
    backtest=BacktestSummary(horizon_days=14, model_mape=0.21, naive_mape=0.34),
    reorders=[
        ReorderSuggestion(
            sku_id=DOLO650.sku_id,
            brand_name=DOLO650.brand_name,
            area="Area A",
            on_hand=12,
            forecast_over_lead_time=40.5,
            reorder_qty=48,
            stockout_risk=True,
            hours_to_stockout=7.5,
        ),
        ReorderSuggestion(
            sku_id=ORS.sku_id,
            brand_name=ORS.brand_name,
            area="Area B",
            on_hand=60,
            forecast_over_lead_time=22.0,
            reorder_qty=0,
            stockout_risk=False,
        ),
    ],
)

FIXTURES = {
    "parsed_rx.json": PARSED,
    "order_pending_review.json": PENDING,
    "order_verified.json": VERIFIED,
    "order_text_otc.json": TEXT_OTC,
    "queue.json": QUEUE,
    "catalog_search.json": SEARCH,
    "samples.json": SAMPLES,
    "forecast_summary.json": SUMMARY,
    "sku_forecast.json": SKU_FORECAST,
}


def dump(value) -> str:
    if isinstance(value, list):
        data = [v.model_dump(mode="json") for v in value]
    else:
        data = value.model_dump(mode="json")
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, value in FIXTURES.items():
        (OUT / name).write_text(dump(value))
    print(f"wrote {len(FIXTURES)} fixtures to {OUT}")
