"""Order rules from contracts/API.md, as pure functions.

Nothing here touches the network, the database or the clock: callers pass in whatever
was looked up. That keeps every rule table-testable (tests/orders/).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from datetime import datetime

from app.contracts import (
    SKU,
    CartItem,
    Confidence,
    ItemDecision,
    MatchResult,
    Order,
    OrderStatus,
    ParsedLine,
    QueueItem,
    ReviewRequest,
    SwapRequest,
    Triage,
)
from app.parser.split import split_request

# ---------------------------------------------------------------------------
# Errors the API maps to HTTP statuses
# ---------------------------------------------------------------------------


class InvalidTransition(Exception):
    """409 invalid_transition."""


class InvalidRequest(Exception):
    """422 invalid_request: the body is well formed but does not fit this order."""


# ---------------------------------------------------------------------------
# Thresholds (contracts/API.md, "Order rules the backend enforces")
# ---------------------------------------------------------------------------

RED_BELOW = 0.6
GREEN_FROM = 0.85

# Weights of the combined score used for sorting. The match dominates; completeness
# and legibility pull it down. The model's self-reported confidence is never used.
W_MATCH, W_COMPLETE, W_LEGIBLE = 0.6, 0.2, 0.2

TRIAGE_RANK: dict[Triage, int] = {"green": 0, "amber": 1, "red": 2}

FIELD_LABEL = {
    "drug": "drug name",
    "strength": "strength",
    "form": "form",
    "frequency": "frequency",
    "duration": "duration",
    "quantity": "quantity",
}


# ---------------------------------------------------------------------------
# Quantity
# ---------------------------------------------------------------------------


def quantity_packs(
    doses_per_day: float | None,
    duration_days: int | None,
    quantity: int | None,
    pack_size: int | None,
) -> tuple[int, str | None]:
    """(packs, reason) for a prescription line.

    `quantity` is in dispensable units, the same unit as `pack_size` (tablets for solid
    forms; bottles, tubes, sachets for the rest, which have pack_size 1). The written
    quantity wins: ceil(quantity / pack); otherwise ceil(doses x days / pack); otherwise
    1 pack, with a reason for the pharmacist.
    """
    if quantity:
        if not pack_size:
            return 1, "no pack size; assumed 1 pack"
        return math.ceil(quantity / pack_size), None
    if doses_per_day is None and duration_days is None:
        return 1, "no dose count or duration; assumed 1 pack"
    if doses_per_day is None:
        return 1, "no dose count (e.g. SOS); assumed 1 pack"
    if duration_days is None:
        return 1, "no duration; assumed 1 pack"
    if not pack_size:
        return 1, "no pack size; assumed 1 pack"
    return max(1, math.ceil(doses_per_day * duration_days / pack_size)), None


MAX_TYPED_PACKS = 20


def packs_from_text(text: str) -> int:
    """Packs for one typed request: '2 strips of dolo' or 'two strips of dolo' -> 2.

    The count comes from the parser's splitter (app.parser.split), the same code that
    split the request, so the two never disagree. Missing or implausible counts -> 1.
    """
    items = split_request(text)
    n = items[0].quantity if items else None
    return n if n is not None and 1 <= n <= MAX_TYPED_PACKS else 1


# ---------------------------------------------------------------------------
# Confidence and triage
# ---------------------------------------------------------------------------


def missing_fields(line: ParsedLine | None) -> list[str]:
    """Which of drug / strength / frequency / duration are absent. A written quantity
    stands in for duration. Typed text has nothing missing."""
    if line is None:
        return []
    present = {
        "drug": line.drug is not None,
        "strength": line.strength is not None,
        "frequency": line.frequency is not None,
        "duration": line.duration_days is not None or line.quantity is not None,
    }
    return [name for name, ok in present.items() if not ok]


def completeness(line: ParsedLine | None) -> float:
    """Share of drug / strength / frequency / duration present. Typed text counts as 1."""
    return 1 - len(missing_fields(line)) / 4


def legibility(line: ParsedLine | None) -> float:
    """1 - illegible fields / fields read, where 'read' means present or flagged."""
    if line is None:
        return 1.0
    values = {
        "drug": line.drug,
        "strength": line.strength,
        "form": line.form,
        "frequency": line.frequency,
        "duration": line.duration_days,
        "quantity": line.quantity,
    }
    illegible = set(line.illegible_fields)
    read = {name for name, v in values.items() if v is not None} | illegible
    if not read:
        return 0.0
    return 1 - len(illegible) / len(read)


def triage(
    has_sku: bool,
    match_score: float,
    complete: float,
    legible: float,
    illegible: Iterable[str],
    missing: Iterable[str] = (),
) -> tuple[Triage, list[str]]:
    """Red / amber / green exactly per contracts/API.md, with a reason for each flag."""
    illegible = list(illegible)
    red: list[str] = []
    if not has_sku:
        red.append("no matching SKU in the catalog")
    if "drug" in illegible:
        red.append("drug name unclear")
    if has_sku and match_score < RED_BELOW:
        red.append(f"weak catalog match ({match_score:.2f})")

    amber: list[str] = []
    if has_sku and RED_BELOW <= match_score < GREEN_FROM:
        amber.append(f"catalog match not certain ({match_score:.2f})")
    if complete < 1:
        # Illegible fields get their own reason below; name only the ones not written.
        unwritten = [FIELD_LABEL.get(f, f) for f in missing if f not in illegible]
        amber.append(f"{', '.join(unwritten)} not written" if unwritten else "prescription line incomplete")
    for field in illegible:
        if field != "drug":
            amber.append(f"{FIELD_LABEL.get(field, field)} unreadable")

    if red:
        return "red", red + amber
    if amber:
        return "amber", amber
    return "green", []


def confidence(match: MatchResult, line: ParsedLine | None, extra_reasons: Iterable[str] = ()) -> Confidence:
    match_score = match.score if match.sku is not None else 0.0
    complete = completeness(line)
    legible = legibility(line)
    illegible = line.illegible_fields if line else []
    level, reasons = triage(
        match.sku is not None, match_score, complete, legible, illegible, missing_fields(line)
    )
    score = W_MATCH * match_score + W_COMPLETE * complete + W_LEGIBLE * legible
    return Confidence(
        score=round(min(1.0, max(0.0, score)), 3),
        match_score=round(match_score, 3),
        completeness=round(complete, 3),
        legibility=round(legible, 3),
        triage=level,
        reasons=reasons + list(extra_reasons),
    )


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------


def money(x: float) -> float:
    return round(x + 0.0, 2)


def savings(sku: SKU | None, generic: SKU | None, packs: int) -> float | None:
    if sku is None or generic is None or generic.mrp_inr >= sku.mrp_inr:
        return None
    return money((sku.mrp_inr - generic.mrp_inr) * packs)


def priced(item: CartItem, brand: SKU | None = None) -> CartItem:
    """Recompute unit price, line total and savings from sku / quantity / generic.

    `brand` is the SKU the customer swapped away from, if they took the generic; savings
    are then measured against it. Otherwise they are measured against `sku`.
    """
    unit = item.sku.mrp_inr if item.sku else 0.0
    base = brand if brand is not None else item.sku
    return item.model_copy(
        update={
            "unit_price_inr": money(unit),
            "line_total_inr": money(unit * item.quantity_packs),
            "savings_inr": savings(base, item.generic_alternative, item.quantity_packs),
        }
    )


def order_total(items: Iterable[CartItem]) -> float:
    """Removed items don't count."""
    return money(sum(i.line_total_inr for i in items if i.status != "removed"))


# ---------------------------------------------------------------------------
# Cart items
# ---------------------------------------------------------------------------


def make_item(
    item_id: str,
    match: MatchResult,
    generic: SKU | None,
    *,
    line: ParsedLine | None = None,
    requested_text: str | None = None,
) -> CartItem:
    sku = match.sku
    if line is not None:
        packs, qty_reason = quantity_packs(
            line.doses_per_day, line.duration_days, line.quantity, sku.pack_size if sku else None
        )
    else:
        packs, qty_reason = packs_from_text(requested_text or ""), None
    extra = [qty_reason] if qty_reason else []
    if match.reason and match.sku is None:
        extra.append(match.reason)
    if generic is not None and sku is not None and generic.mrp_inr >= sku.mrp_inr:
        generic = None
    item = CartItem(
        item_id=item_id,
        parsed=line,
        requested_text=requested_text,
        sku=sku,
        quantity_packs=packs,
        unit_price_inr=0,
        line_total_inr=0,
        generic_alternative=generic if sku is not None else None,
        confidence=confidence(match, line, extra),
    )
    return priced(item)


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    "pending_review": frozenset({"verified", "rejected"}),
    "verified": frozenset({"placed"}),
    "confirmed_otc": frozenset({"placed"}),
    "rejected": frozenset(),
    "needs_prescription": frozenset(),
    "placed": frozenset(),
}

SWAPPABLE: frozenset[OrderStatus] = frozenset({"pending_review", "confirmed_otc"})


def check_transition(current: OrderStatus, target: OrderStatus) -> None:
    if target not in TRANSITIONS[current]:
        raise InvalidTransition(f"order is {current}; cannot move to {target}")


def text_order_status(items: Iterable[CartItem]) -> OrderStatus:
    """confirmed_otc only if every matched item is OTC."""
    return (
        "needs_prescription" if any(i.sku is not None and i.sku.rx_only for i in items) else "confirmed_otc"
    )


# ---------------------------------------------------------------------------
# Customer swap
# ---------------------------------------------------------------------------


def apply_swap(
    order: Order, req: SwapRequest, swapped_from: Mapping[str, SKU]
) -> tuple[Order, dict[str, SKU]]:
    """Take or undo the generic alternative on one item.

    After a swap, `sku` and `generic_alternative` are the same generic SKU and
    `savings_inr` is what the customer saves. `swapped_from` remembers the brand so
    the swap can be undone; the updated map is returned alongside the order.
    """
    if order.status not in SWAPPABLE:
        raise InvalidTransition(f"order is {order.status}; swaps are only allowed before review")
    idx = _index(order, req.item_id)
    item = order.items[idx]
    originals = dict(swapped_from)
    taken = item.item_id in originals

    if req.use_generic:
        if taken:
            return order, originals
        if item.sku is None or item.generic_alternative is None:
            raise InvalidRequest(f"{item.item_id} has no generic alternative")
        brand = item.sku
        new = priced(item.model_copy(update={"sku": item.generic_alternative}), brand)
        originals[item.item_id] = brand
    else:
        if not taken:
            return order, originals
        new = priced(item.model_copy(update={"sku": originals.pop(item.item_id)}))

    items = list(order.items)
    items[idx] = new
    return order.model_copy(update={"items": items, "total_inr": order_total(items)}), originals


# ---------------------------------------------------------------------------
# Pharmacist review
# ---------------------------------------------------------------------------


def edit_sku_ids(req: ReviewRequest) -> set[str]:
    """SKUs the caller must look up before calling apply_review."""
    return {d.sku_id for d in req.items if d.action == "edit" and d.sku_id}


def apply_review(
    order: Order,
    req: ReviewRequest,
    skus: Mapping[str, SKU | None],
    generics: Mapping[str, SKU | None],
    now: datetime,
    swapped_from: Mapping[str, SKU] | None = None,
) -> Order:
    """Apply a ReviewRequest. `skus` holds every id from edit_sku_ids (None if unknown);
    `generics` maps those ids to their cheapest generic; `swapped_from` is the customer's
    generic swaps, so savings stay measured against the brand they gave up."""
    target: OrderStatus = "verified" if req.decision == "approve" else "rejected"
    check_transition(order.status, target)

    decisions: dict[str, ItemDecision] = {}
    known = {i.item_id for i in order.items}
    for d in req.items:
        if d.item_id not in known:
            raise InvalidRequest(f"unknown item_id {d.item_id}")
        if d.item_id in decisions:
            raise InvalidRequest(f"{d.item_id} listed twice")
        decisions[d.item_id] = d

    items = order.items
    if req.decision == "approve":
        swaps = swapped_from or {}
        items = [
            _decide(item, decisions.get(item.item_id), skus, generics, swaps.get(item.item_id))
            for item in order.items
        ]
        for item in items:
            if item.status != "removed" and item.sku is None:
                raise InvalidRequest(f"{item.item_id} has no SKU; edit or remove it before approving")

    return order.model_copy(
        update={
            "status": target,
            "items": items,
            "total_inr": order_total(items),
            "pharmacist_note": req.note,
            "reviewed_at": now,
        }
    )


def _decide(
    item: CartItem,
    d: ItemDecision | None,
    skus: Mapping[str, SKU | None],
    generics: Mapping[str, SKU | None],
    brand: SKU | None,
) -> CartItem:
    if d is None:
        return item.model_copy(update={"status": "approved"})
    if d.action == "remove":
        return item.model_copy(update={"status": "removed"})
    update: dict[str, object] = {"status": "approved" if d.action == "approve" else "edited"}
    if d.quantity_packs is not None:
        update["quantity_packs"] = d.quantity_packs
    if d.action == "edit":
        if d.sku_id is None and d.quantity_packs is None:
            raise InvalidRequest(f"edit on {d.item_id} needs sku_id or quantity_packs")
        if d.sku_id is not None and d.sku_id != (item.sku.sku_id if item.sku else None):
            sku = skus.get(d.sku_id)
            if sku is None:
                raise InvalidRequest(f"unknown sku_id {d.sku_id}")
            generic = generics.get(d.sku_id)
            update["sku"] = sku
            update["generic_alternative"] = generic if generic and generic.mrp_inr < sku.mrp_inr else None
            brand = None
    return priced(item.model_copy(update=update), brand)


def _index(order: Order, item_id: str) -> int:
    for idx, item in enumerate(order.items):
        if item.item_id == item_id:
            return idx
    raise InvalidRequest(f"unknown item_id {item_id}")


# ---------------------------------------------------------------------------
# Pharmacist queue
# ---------------------------------------------------------------------------


def worst_triage(items: Iterable[CartItem]) -> Triage:
    worst: Triage = "green"
    for item in items:
        if item.status != "removed" and TRIAGE_RANK[item.confidence.triage] > TRIAGE_RANK[worst]:
            worst = item.confidence.triage
    return worst


def queue_item(order: Order) -> QueueItem:
    counts: dict[Triage, int] = {"green": 0, "amber": 0, "red": 0}
    live = [i for i in order.items if i.status != "removed"]
    for item in live:
        counts[item.confidence.triage] += 1
    return QueueItem(
        order_id=order.order_id,
        created_at=order.created_at,
        source=order.source,
        item_count=len(live),
        counts=counts,
        worst_triage=worst_triage(live),
        total_inr=order.total_inr,
    )


def build_queue(orders: Iterable[Order]) -> list[QueueItem]:
    """Only pending_review; worst triage first, then oldest first."""
    rows = [queue_item(o) for o in orders if o.status == "pending_review"]
    return sorted(rows, key=lambda q: (-TRIAGE_RANK[q.worst_triage], q.created_at))
