"""Table-driven tests for the pure order rules (contracts/API.md, 'Order rules')."""

from datetime import UTC, datetime, timedelta

import pytest

from app.contracts import (
    SKU,
    CartItem,
    Confidence,
    ItemDecision,
    MatchResult,
    Order,
    ParsedLine,
    ReviewRequest,
    Salt,
    SwapRequest,
)
from app.orders import rules
from app.orders.rules import InvalidRequest, InvalidTransition

T0 = datetime(2026, 9, 30, 10, 0, tzinfo=UTC)


def sku(sku_id="sku_a", mrp=100.0, pack=10, rx=True, key="drug 500mg") -> SKU:
    return SKU(
        sku_id=sku_id,
        brand_name=sku_id.upper(),
        manufacturer="M",
        form="tablet",
        pack_size=pack,
        pack_label=f"strip of {pack}",
        mrp_inr=mrp,
        composition=[Salt(name="drug", strength="500mg")],
        composition_key=key,
        rx_only=rx,
        schedule="H" if rx else None,
    )


BRAND = sku("sku_brand", 200.0)
GENERIC = sku("sku_generic", 120.0)
OTHER = sku("sku_other", 50.0, pack=15, key="other 10mg")


def line(**kw) -> ParsedLine:
    base = {
        "line_no": 1,
        "raw_text": "Tab X 500 1-0-1 x 5d",
        "drug": "X",
        "strength": "500",
        "form": "tablet",
        "frequency": "1-0-1",
        "doses_per_day": 2,
        "duration_days": 5,
    }
    return ParsedLine(**(base | kw))


def match(s: SKU | None = BRAND, score=0.95) -> MatchResult:
    return MatchResult(sku=s, score=score, candidates=[], reranked=False)


# ---------------------------------------------------------------------------
# quantity_packs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "doses,days,qty,pack,expected,has_reason",
    [
        (2, 5, None, 10, 1, False),  # 10 tabs, strip of 10
        (3, 5, None, 10, 2, False),  # 15 tabs -> ceil 1.5
        (2, 7, None, 10, 2, False),  # 14 tabs
        (1, 30, None, 15, 2, False),  # 30 tabs, strip of 15
        (0.5, 10, None, 10, 1, False),  # half a tab a day
        (0, 5, None, 10, 1, False),  # never fewer than 1 pack
        (2, 5, 30, 10, 3, False),  # written quantity (units) wins over doses x days
        (2, 5, 10, 10, 1, False),  # exactly one strip
        (None, None, 21, 10, 3, False),  # written quantity even without inputs: ceil(21/10)
        (None, None, 1, 15, 1, False),  # a single tablet still needs a pack
        (None, None, 2, 1, 2, False),  # 2 bottles, pack_size 1
        (None, None, 5, None, 1, True),  # quantity but no pack size (no SKU)
        (2, 5, 0, 10, 1, False),  # quantity 0 means "not written"
        (None, 5, None, 10, 1, True),  # SOS: no dose count
        (2, None, None, 10, 1, True),  # no duration
        (None, None, None, 10, 1, True),  # neither
        (2, 5, None, None, 1, True),  # no pack size (no SKU)
    ],
)
def test_quantity_packs(doses, days, qty, pack, expected, has_reason):
    packs, reason = rules.quantity_packs(doses, days, qty, pack)
    assert packs == expected
    assert (reason is not None) == has_reason


@pytest.mark.parametrize(
    "text,expected",
    [
        ("dolo", 1),
        ("2 dolo", 2),
        ("3 strips of crocin", 3),
        ("two strips of dolo", 2),
        ("please send 2 strips of dolo", 2),
        ("dolo x 3", 3),
        ("2x ORS", 2),
        ("dolo 650", 1),
        ("99 dolo", 1),
    ],
)
def test_packs_from_text(text, expected):
    assert rules.packs_from_text(text) == expected


# ---------------------------------------------------------------------------
# completeness, legibility, triage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kw,expected",
    [
        ({}, 1.0),
        ({"duration_days": None}, 0.75),
        ({"duration_days": None, "quantity": 10}, 1.0),  # an explicit count stands in for duration
        ({"duration_days": None, "frequency": None}, 0.5),
        ({"drug": None, "strength": None, "frequency": None, "duration_days": None}, 0.0),
    ],
)
def test_completeness(kw, expected):
    assert rules.completeness(line(**kw)) == expected


def test_completeness_and_legibility_of_typed_text():
    assert rules.completeness(None) == 1.0
    assert rules.legibility(None) == 1.0


@pytest.mark.parametrize(
    "kw,expected",
    [
        ({}, 1.0),
        ({"duration_days": None, "illegible_fields": ["duration"]}, 0.8),  # 4 read + 1 flagged
        ({"illegible_fields": ["drug"]}, 1 - 1 / 5),
        ({"illegible_fields": ["drug", "strength"]}, 1 - 2 / 5),
    ],
)
def test_legibility(kw, expected):
    assert rules.legibility(line(**kw)) == pytest.approx(expected)


@pytest.mark.parametrize(
    "has_sku,score,complete,illegible,expected",
    [
        (True, 0.95, 1.0, [], "green"),
        (True, 0.85, 1.0, [], "green"),  # boundary: 0.85 is green
        (True, 0.849, 1.0, [], "amber"),
        (True, 0.6, 1.0, [], "amber"),  # boundary: 0.6 is amber
        (True, 0.599, 1.0, [], "red"),
        (True, 0.95, 0.75, [], "amber"),  # incomplete
        (True, 0.95, 1.0, ["strength"], "amber"),  # a non-drug field illegible
        (True, 0.95, 1.0, ["drug"], "red"),  # drug illegible
        (False, 0.0, 1.0, [], "red"),  # no SKU
        (False, 0.9, 1.0, [], "red"),  # no SKU even with a score
    ],
)
def test_triage(has_sku, score, complete, illegible, expected):
    level, reasons = rules.triage(has_sku, score, complete, 1.0, illegible)
    assert level == expected
    assert (len(reasons) > 0) == (level != "green"), "every amber and red is explained"


@pytest.mark.parametrize(
    "kw,reason",
    [
        ({"strength": None}, "strength not written"),
        ({"strength": None, "duration_days": None}, "strength, duration not written"),
        # an illegible field is reported as unreadable, not as missing
        ({"duration_days": None, "illegible_fields": ["duration"]}, "duration unreadable"),
    ],
)
def test_incomplete_reason_names_fields(kw, reason):
    c = rules.confidence(match(BRAND), line(**kw))
    assert c.triage == "amber"
    assert reason in c.reasons


def test_confidence_uses_zero_match_when_no_sku():
    c = rules.confidence(match(None, 0.9), line())
    assert c.match_score == 0.0
    assert c.triage == "red"
    assert 0 <= c.score <= 1


def test_confidence_score_orders_sensibly():
    good = rules.confidence(match(BRAND, 0.97), line())
    meh = rules.confidence(match(BRAND, 0.7), line(duration_days=None, illegible_fields=["duration"]))
    assert good.score > meh.score


# ---------------------------------------------------------------------------
# make_item, pricing, totals
# ---------------------------------------------------------------------------


def test_make_item_prices_and_generic():
    item = rules.make_item("itm_1", match(BRAND), GENERIC, line=line(doses_per_day=3, duration_days=5))
    assert item.quantity_packs == 2
    assert item.unit_price_inr == 200.0
    assert item.line_total_inr == 400.0
    assert item.generic_alternative == GENERIC
    assert item.savings_inr == 160.0
    assert item.confidence.triage == "green"
    assert item.status == "pending"


def test_make_item_drops_a_generic_that_is_not_cheaper():
    item = rules.make_item("itm_1", match(GENERIC), BRAND, line=line())
    assert item.generic_alternative is None
    assert item.savings_inr is None


def test_make_item_without_sku_is_red_and_free():
    item = rules.make_item("itm_1", match(None, 0.3), None, line=line())
    assert item.sku is None
    assert item.line_total_inr == 0
    assert item.confidence.triage == "red"


def test_make_item_quantity_reason_lands_on_item():
    item = rules.make_item("itm_1", match(BRAND), None, line=line(doses_per_day=None, frequency="SOS"))
    assert item.quantity_packs == 1
    assert any("assumed 1 pack" in r for r in item.confidence.reasons)


def test_make_item_written_quantity_is_units():
    # "Tab X 500, #15": 15 tablets from strips of 10 -> 2 strips
    item = rules.make_item("itm_1", match(BRAND), None, line=line(quantity=15))
    assert item.quantity_packs == 2
    assert item.line_total_inr == 400.0


def test_make_text_item():
    item = rules.make_item("itm_1", match(OTHER, 0.9), None, requested_text="2 other")
    assert item.parsed is None
    assert item.requested_text == "2 other"
    assert item.quantity_packs == 2
    assert item.line_total_inr == 100.0
    assert item.confidence.triage == "green"


def _item(item_id, price, status="pending", triage="green") -> CartItem:
    s = sku(f"sku_{item_id}", price)
    return CartItem(
        item_id=item_id,
        sku=s,
        quantity_packs=1,
        unit_price_inr=price,
        line_total_inr=price,
        confidence=Confidence(score=0.9, match_score=0.9, completeness=1, legibility=1, triage=triage),
        status=status,
    )


def test_order_total_skips_removed():
    items = [_item("a", 10.1), _item("b", 20.2, "removed"), _item("c", 0.35, "edited")]
    assert rules.order_total(items) == 10.45


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

ALLOWED = {
    ("pending_review", "verified"),
    ("pending_review", "rejected"),
    ("verified", "placed"),
    ("confirmed_otc", "placed"),
}
STATUSES = ["pending_review", "verified", "rejected", "confirmed_otc", "needs_prescription", "placed"]


@pytest.mark.parametrize("current", STATUSES)
@pytest.mark.parametrize("target", STATUSES)
def test_transitions(current, target):
    if (current, target) in ALLOWED:
        rules.check_transition(current, target)
    else:
        with pytest.raises(InvalidTransition):
            rules.check_transition(current, target)


@pytest.mark.parametrize(
    "rx_flags,expected",
    [
        ([False, False], "confirmed_otc"),
        ([False, True], "needs_prescription"),
        ([True], "needs_prescription"),
        ([False, None], "confirmed_otc"),  # None = unmatched, does not force Rx
    ],
)
def test_text_order_status(rx_flags, expected):
    items = []
    for i, rx in enumerate(rx_flags):
        m = match(None, 0.2) if rx is None else match(sku(f"s{i}", rx=rx), 0.9)
        items.append(rules.make_item(f"itm_{i}", m, None, requested_text="x"))
    assert rules.text_order_status(items) == expected


# ---------------------------------------------------------------------------
# Orders for swap / review / queue
# ---------------------------------------------------------------------------


def order(items, status="pending_review", created=T0, source="prescription") -> Order:
    return Order(
        order_id=f"ord_{created.minute}_{status}",
        created_at=created,
        source=source,
        status=status,
        has_image=True,
        items=items,
        total_inr=rules.order_total(items),
        requires_review=True,
    )


def rx_order(status="pending_review") -> Order:
    items = [
        rules.make_item("itm_1", match(BRAND), GENERIC, line=line()),
        rules.make_item("itm_2", match(OTHER, 0.7), None, line=line(line_no=2)),
        rules.make_item("itm_3", match(None, 0.3), None, line=line(line_no=3, illegible_fields=["drug"])),
    ]
    return order(items, status)


def test_swap_to_generic_and_back():
    o = rx_order()
    swapped, memory = rules.apply_swap(o, SwapRequest(item_id="itm_1", use_generic=True), {})
    item = swapped.items[0]
    assert item.sku == GENERIC
    assert item.generic_alternative == GENERIC
    assert item.savings_inr == 80.0
    assert swapped.total_inr == o.total_inr - 80.0
    assert memory == {"itm_1": BRAND}

    again, memory2 = rules.apply_swap(swapped, SwapRequest(item_id="itm_1", use_generic=True), memory)
    assert again == swapped, "taking the generic twice is a no-op"

    back, memory3 = rules.apply_swap(swapped, SwapRequest(item_id="itm_1", use_generic=False), memory2)
    assert back.items[0].sku == BRAND
    assert back.items[0].savings_inr == 80.0
    assert back.total_inr == o.total_inr
    assert memory3 == {}


@pytest.mark.parametrize(
    "item_id,status,error",
    [
        ("itm_2", "pending_review", InvalidRequest),  # no generic
        ("itm_9", "pending_review", InvalidRequest),  # unknown item
        ("itm_1", "verified", InvalidTransition),  # after review
        ("itm_1", "placed", InvalidTransition),
    ],
)
def test_swap_errors(item_id, status, error):
    with pytest.raises(error):
        rules.apply_swap(rx_order(status), SwapRequest(item_id=item_id, use_generic=True), {})


def test_review_approve_with_edit_and_remove():
    o = rx_order()
    req = ReviewRequest(
        decision="approve",
        items=[
            ItemDecision(item_id="itm_2", action="edit", quantity_packs=3),
            ItemDecision(item_id="itm_3", action="edit", sku_id="sku_brand", quantity_packs=2),
        ],
        note="ok",
    )
    out = rules.apply_review(o, req, {"sku_brand": BRAND}, {"sku_brand": GENERIC}, T0)
    assert out.status == "verified"
    assert out.reviewed_at == T0
    assert out.pharmacist_note == "ok"
    s = {i.item_id: i for i in out.items}
    assert s["itm_1"].status == "approved"  # not listed -> approved as is
    assert s["itm_2"].status == "edited" and s["itm_2"].quantity_packs == 3
    assert s["itm_2"].line_total_inr == 150.0
    assert s["itm_3"].sku == BRAND and s["itm_3"].line_total_inr == 400.0
    assert s["itm_3"].generic_alternative == GENERIC and s["itm_3"].savings_inr == 160.0
    assert out.total_inr == 200.0 + 150.0 + 400.0


def test_review_remove_excludes_from_total():
    req = ReviewRequest(decision="approve", items=[ItemDecision(item_id="itm_3", action="remove")])
    out = rules.apply_review(rx_order(), req, {}, {}, T0)
    assert out.items[2].status == "removed"
    assert out.total_inr == 200.0 + 50.0


def test_review_reject_keeps_items():
    o = rx_order()
    out = rules.apply_review(o, ReviewRequest(decision="reject", note="illegible"), {}, {}, T0)
    assert out.status == "rejected"
    assert out.items == o.items
    assert out.pharmacist_note == "illegible"


@pytest.mark.parametrize(
    "req,status,skus,error",
    [
        (ReviewRequest(decision="approve"), "pending_review", {}, InvalidRequest),  # itm_3 has no SKU
        (ReviewRequest(decision="approve"), "verified", {}, InvalidTransition),
        (ReviewRequest(decision="reject"), "placed", {}, InvalidTransition),
        (
            ReviewRequest(decision="approve", items=[ItemDecision(item_id="nope", action="remove")]),
            "pending_review",
            {},
            InvalidRequest,
        ),
        (
            ReviewRequest(
                decision="approve", items=[ItemDecision(item_id="itm_3", action="edit", sku_id="sku_zzz")]
            ),
            "pending_review",
            {"sku_zzz": None},
            InvalidRequest,
        ),
        (
            ReviewRequest(decision="approve", items=[ItemDecision(item_id="itm_3", action="edit")]),
            "pending_review",
            {},
            InvalidRequest,
        ),
        (
            ReviewRequest(
                decision="approve",
                items=[
                    ItemDecision(item_id="itm_3", action="remove"),
                    ItemDecision(item_id="itm_3", action="remove"),
                ],
            ),
            "pending_review",
            {},
            InvalidRequest,
        ),
    ],
)
def test_review_errors(req, status, skus, error):
    with pytest.raises(error):
        rules.apply_review(rx_order(status), req, skus, {}, T0)


def test_review_keeps_savings_for_a_swapped_item():
    o = rx_order()
    swapped, memory = rules.apply_swap(o, SwapRequest(item_id="itm_1", use_generic=True), {})
    req = ReviewRequest(
        decision="approve",
        items=[
            ItemDecision(item_id="itm_1", action="approve", quantity_packs=2),
            ItemDecision(item_id="itm_3", action="remove"),
        ],
    )
    out = rules.apply_review(swapped, req, {}, {}, T0, memory)
    assert out.items[0].sku == GENERIC
    assert out.items[0].savings_inr == 160.0


def test_edit_sku_ids():
    req = ReviewRequest(
        decision="approve",
        items=[
            ItemDecision(item_id="a", action="edit", sku_id="x"),
            ItemDecision(item_id="b", action="edit", quantity_packs=2),
            ItemDecision(item_id="c", action="approve", sku_id="y"),
        ],
    )
    assert rules.edit_sku_ids(req) == {"x"}


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------


def test_queue_item_counts_and_worst():
    o = order([_item("a", 1, triage="green"), _item("b", 1, triage="amber"), _item("c", 1, triage="red")])
    q = rules.queue_item(o)
    assert q.counts == {"green": 1, "amber": 1, "red": 1}
    assert q.worst_triage == "red"
    assert q.item_count == 3


def test_queue_ordering_worst_first_then_oldest():
    def at(minutes, triage, status="pending_review"):
        return order([_item("a", 1, triage=triage)], status, T0 + timedelta(minutes=minutes))

    orders = [
        at(1, "green"),
        at(2, "red"),
        at(3, "amber"),
        at(4, "red"),
        at(0, "green"),
        at(5, "red", status="verified"),  # not pending: excluded
    ]
    queue = rules.build_queue(orders)
    assert [(q.worst_triage, q.created_at.minute) for q in queue] == [
        ("red", 2),
        ("red", 4),
        ("amber", 3),
        ("green", 0),
        ("green", 1),
    ]


def test_queue_empty_order_is_green():
    assert rules.worst_triage([]) == "green"
