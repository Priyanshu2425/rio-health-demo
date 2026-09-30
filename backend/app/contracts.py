"""Shared data contracts for Rio.

Every branch builds against these models. They are frozen on `main`: a feature branch
never edits this file. If you need a change, stop and ask for a `chore/contracts-vN`
branch. `frontend/src/contracts.gen.ts` and `contracts/schema.json` are generated from
this file by `backend/scripts/export_schema.py`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    """Base for every contract model. In the exported schema, fields with defaults are
    still marked required for responses, because the API always sends them."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


# ---------------------------------------------------------------------------
# Shared vocabulary
# ---------------------------------------------------------------------------

Form = Literal[
    "tablet",
    "capsule",
    "syrup",
    "suspension",
    "injection",
    "cream",
    "ointment",
    "gel",
    "drops",
    "inhaler",
    "powder",
    "sachet",
    "other",
]
"""Dosage form. Catalog ETL and the parser both map onto this list."""

Schedule = Literal["H", "H1", "X"]
"""Drugs and Cosmetics Rules schedule. Any of these makes a SKU prescription-only."""

Triage = Literal["green", "amber", "red"]
"""green: approve as is. amber: check against the image. red: pharmacist must edit."""

ParsedField = Literal["drug", "strength", "form", "frequency", "duration", "quantity"]


# ---------------------------------------------------------------------------
# Parser output
# ---------------------------------------------------------------------------


class ParsedLine(Contract):
    """One medicine line as read off the prescription. No catalog knowledge."""

    line_no: int = Field(ge=1, description="1-based position on the prescription")
    raw_text: str = Field(description="The line exactly as written, for the pharmacist")
    drug: str | None = Field(None, description="Brand or generic name as written, e.g. 'Augmentin'")
    strength: str | None = Field(None, description="As written, e.g. '625', '500/125 mg', '5 ml'")
    form: Form | None = None
    frequency: str | None = Field(None, description="As written, e.g. '1-0-1', 'BD', 'SOS'")
    doses_per_day: float | None = Field(
        None, ge=0, description="Normalized from frequency: '1-0-1' -> 2, 'TDS' -> 3, 'SOS' -> null"
    )
    duration_days: int | None = Field(None, ge=0)
    quantity: int | None = Field(
        None,
        ge=0,
        description=(
            "Explicit count written on the Rx, in the same units as SKU.pack_size: tablets or "
            "capsules for solid forms ('#10' -> 10), bottles/tubes/sachets/inhalers otherwise. "
            "Null when absent or when written in packs ('2 strips')"
        ),
    )
    illegible_fields: list[ParsedField] = Field(
        default_factory=list, description="Fields the model could not read with confidence"
    )
    bbox: list[float] | None = Field(
        None,
        min_length=4,
        max_length=4,
        description="Optional [x0, y0, x1, y1] in 0..1 image coordinates; UI falls back to the full image",
    )


class ParsedRx(Contract):
    """Everything the vision model extracted from one prescription image."""

    doctor_name: str | None = None
    clinic_name: str | None = None
    patient_name: str | None = None
    rx_date: date | None = None
    lines: list[ParsedLine]
    model: str = Field(description="OpenRouter model id that produced this parse")
    latency_ms: int = Field(ge=0)
    cost_usd: float | None = Field(None, ge=0)


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


class Salt(Contract):
    name: str = Field(description="Normalized lowercase salt, e.g. 'amoxycillin'")
    strength: str | None = Field(None, description="Normalized, e.g. '500mg', '5mg/ml'")


class SKU(Contract):
    sku_id: str
    brand_name: str
    manufacturer: str
    form: Form
    pack_size: int = Field(
        ge=1,
        description=(
            "Dispensable units per pack: tablets/capsules per strip or bottle (strip of 10 -> 10); "
            "vials per pack for injections; 1 for anything sold by volume or weight (syrup, drops, "
            "cream, inhaler) and for sachets, with the volume in pack_label"
        ),
    )
    pack_label: str = Field(description="Human label, e.g. 'strip of 10 tablets'")
    mrp_inr: float = Field(ge=0, description="Price per pack in rupees")
    composition: list[Salt]
    composition_key: str = Field(
        description="Canonical sorted 'salt strength + salt strength'; equal keys = substitutable"
    )
    rx_only: bool
    schedule: Schedule | None = None


class MatchCandidate(Contract):
    sku: SKU
    score: float = Field(ge=0, le=1, description="Trigram or re-rank score")


class MatchResult(Contract):
    """What the matcher decided for one ParsedLine."""

    sku: SKU | None = Field(description="Chosen SKU, or null when nothing fits")
    score: float = Field(ge=0, le=1)
    candidates: list[MatchCandidate] = Field(description="Top candidates considered, best first")
    reranked: bool = Field(description="True when the LLM re-rank ran")
    reason: str | None = None


# ---------------------------------------------------------------------------
# Cart and orders
# ---------------------------------------------------------------------------


class Confidence(Contract):
    score: float = Field(ge=0, le=1, description="Combined score used for sorting")
    match_score: float = Field(ge=0, le=1)
    completeness: float = Field(ge=0, le=1, description="Share of drug/strength/frequency/duration present")
    legibility: float = Field(ge=0, le=1, description="1 - illegible fields / fields read")
    triage: Triage
    reasons: list[str] = Field(
        default_factory=list, description="Short, pharmacist-facing, e.g. 'strength unreadable'"
    )


CartItemStatus = Literal["pending", "approved", "edited", "removed"]


class CartItem(Contract):
    item_id: str
    parsed: ParsedLine | None = Field(None, description="Null for typed-text orders")
    requested_text: str | None = Field(None, description="The typed request, for text orders")
    sku: SKU | None = Field(description="Null when nothing matched; always red")
    quantity_packs: int = Field(ge=0)
    unit_price_inr: float = Field(ge=0)
    line_total_inr: float = Field(ge=0)
    generic_alternative: SKU | None = Field(None, description="Cheapest SKU with the same composition_key")
    savings_inr: float | None = Field(None, ge=0, description="Per line, if the customer swaps")
    confidence: Confidence
    status: CartItemStatus = "pending"


OrderSource = Literal["prescription", "sample", "text"]

OrderStatus = Literal[
    "pending_review",  # prescription order waiting for a pharmacist
    "verified",  # pharmacist approved; customer can place it
    "rejected",  # pharmacist rejected; see pharmacist_note
    "confirmed_otc",  # text order with only OTC items; no review needed
    "needs_prescription",  # text order asked for an Rx-only item
    "placed",  # customer pressed "Place order" (stub)
]


class Order(Contract):
    order_id: str
    created_at: datetime
    source: OrderSource
    status: OrderStatus
    has_image: bool = Field(description="GET /api/orders/{id}/image serves it when true")
    parsed_rx: ParsedRx | None = None
    items: list[CartItem]
    total_inr: float = Field(ge=0)
    requires_review: bool
    pharmacist_note: str | None = None
    reviewed_at: datetime | None = None


class QueueItem(Contract):
    """One row in the pharmacist queue. Worst triage first, then oldest first."""

    order_id: str
    created_at: datetime
    source: OrderSource
    item_count: int
    counts: dict[Triage, int]
    worst_triage: Triage
    total_inr: float


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


class TextOrderRequest(Contract):
    text: str = Field(min_length=1, max_length=500)


class SwapRequest(Contract):
    item_id: str
    use_generic: bool


class ItemDecision(Contract):
    item_id: str
    action: Literal["approve", "edit", "remove"]
    sku_id: str | None = Field(None, description="Required for edit when changing the SKU")
    quantity_packs: int | None = Field(None, ge=1)


class ReviewRequest(Contract):
    decision: Literal["approve", "reject"]
    items: list[ItemDecision] = Field(default_factory=list, description="Items not listed are approved as is")
    note: str | None = None


class Sample(Contract):
    sample_id: str
    label: str = Field(description="e.g. 'Typed clinic Rx, 3 lines'")
    thumbnail_url: str


class ApiError(Contract):
    code: str
    message: str


class ErrorResponse(Contract):
    error: ApiError


# ---------------------------------------------------------------------------
# Forecast
# ---------------------------------------------------------------------------


class ForecastPoint(Contract):
    ts: datetime = Field(description="Start of the hour, Asia/Kolkata")
    forecast: float = Field(ge=0)
    actual: float | None = Field(None, ge=0, description="Present inside the backtest window")


class SkuForecast(Contract):
    sku_id: str
    brand_name: str
    area: str
    points: list[ForecastPoint]
    model_mape: float = Field(ge=0, description="Backtest error of our model on this series")
    naive_mape: float = Field(ge=0, description="Same hour last week")


class ReorderSuggestion(Contract):
    sku_id: str
    brand_name: str
    area: str
    on_hand: int = Field(ge=0)
    forecast_over_lead_time: float = Field(ge=0)
    reorder_qty: int = Field(ge=0)
    stockout_risk: bool
    hours_to_stockout: float | None = Field(None, ge=0)


class SkuRef(Contract):
    sku_id: str
    brand_name: str


class BacktestSummary(Contract):
    horizon_days: int
    model_mape: float
    naive_mape: float


class ForecastSummary(Contract):
    generated_at: datetime
    areas: list[str]
    skus: list[SkuRef] = Field(description="SKUs that have forecasts, for the picker")
    backtest: BacktestSummary
    reorders: list[ReorderSuggestion] = Field(description="Stockout risks first")
