"""PostgresOrders against the real `orders` table.

Marked `db`: needs RIO_HEALTH_DATABASE_URL. Every order it writes has an id starting
with `ord_test_<run>`, and they are all deleted afterwards. No other table is touched.
"""

import secrets
from datetime import UTC, datetime, timedelta

import pytest
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from app.contracts import SKU, CartItem, Confidence, Order, ParsedLine, ParsedRx, Salt
from app.core.config import get_settings
from app.orders import rules
from app.orders.repo import OrderRecord, PostgresOrders, StaleOrder

pytestmark = pytest.mark.db

RUN = f"ord_test_{secrets.token_hex(4)}"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x01\x02" * 16


@pytest.fixture
async def conn():
    settings = get_settings()
    if not settings.database_url:
        pytest.skip("RIO_HEALTH_DATABASE_URL is not set")
    connection = await AsyncConnection.connect(settings.database_url, row_factory=dict_row)
    await connection.execute(f"SET search_path TO {settings.db_schema}, public")
    try:
        yield connection
    finally:
        await connection.rollback()
        await connection.execute("DELETE FROM orders WHERE left(order_id, %s) = %s", (len(RUN), RUN))
        await connection.commit()
        await connection.close()


def _sku(sku_id: str, mrp: float) -> SKU:
    return SKU(
        sku_id=sku_id,
        brand_name=sku_id,
        manufacturer="Test",
        form="tablet",
        pack_size=10,
        pack_label="strip of 10 tablets",
        mrp_inr=mrp,
        composition=[Salt(name="testol", strength="10mg")],
        composition_key="testol 10mg",
        rx_only=True,
        schedule="H",
    )


BRAND, GENERIC = _sku("sku_test_brand", 123.45), _sku("sku_test_generic", 67.8)
LINE = ParsedLine(line_no=1, raw_text="Tab Testol 10 1-0-1 x 5d", drug="Testol", strength="10")


def _order(suffix: str, status="pending_review", created=None, triage="green") -> Order:
    item = CartItem(
        item_id="itm_1",
        parsed=LINE,
        sku=BRAND,
        quantity_packs=2,
        unit_price_inr=BRAND.mrp_inr,
        line_total_inr=246.9,
        generic_alternative=GENERIC,
        savings_inr=111.3,
        confidence=Confidence(
            score=0.9, match_score=0.9, completeness=0.75, legibility=1, triage=triage, reasons=["x"]
        ),
    )
    return Order(
        order_id=f"{RUN}_{suffix}",
        created_at=created or datetime.now(UTC),
        source="sample",
        status=status,
        has_image=True,
        parsed_rx=ParsedRx(lines=[LINE], model="test/model", latency_ms=12, cost_usd=0.001),
        items=[item],
        total_inr=246.9,
        requires_review=True,
    )


async def test_round_trip(conn):
    repo = PostgresOrders()
    order = _order("rt")
    await repo.create(conn, OrderRecord(order, PNG, "image/png"))
    got = await repo.get(conn, order.order_id)
    assert got is not None
    assert got.order == order
    assert got.image is None, "get() leaves the bytes to get_image()"
    assert await repo.get_image(conn, order.order_id) == (PNG, "image/png")


async def test_missing(conn):
    repo = PostgresOrders()
    assert await repo.get(conn, f"{RUN}_nope") is None
    assert await repo.get_image(conn, f"{RUN}_nope") is None


async def test_order_without_image(conn):
    repo = PostgresOrders()
    order = _order("noimg").model_copy(update={"has_image": False, "parsed_rx": None, "source": "text"})
    await repo.create(conn, OrderRecord(order))
    got = await repo.get(conn, order.order_id)
    assert got.order == order
    assert await repo.get_image(conn, order.order_id) is None


async def test_save_keeps_swaps_and_checks_status(conn):
    from app.contracts import SwapRequest

    repo = PostgresOrders()
    order = _order("swap")
    await repo.create(conn, OrderRecord(order, PNG, "image/png"))

    swapped, memory = rules.apply_swap(order, SwapRequest(item_id="itm_1", use_generic=True), {})
    await repo.save(conn, OrderRecord(swapped, swapped_from=memory), "pending_review")
    got = await repo.get(conn, order.order_id)
    assert got.order == swapped
    assert got.swapped_from == {"itm_1": BRAND}
    assert await repo.get_image(conn, order.order_id) == (PNG, "image/png"), "save keeps the image"

    reviewed = swapped.model_copy(
        update={"status": "verified", "reviewed_at": datetime.now(UTC), "pharmacist_note": "ok"}
    )
    await repo.save(conn, OrderRecord(reviewed, swapped_from=memory), "pending_review")
    assert (await repo.get(conn, order.order_id)).order == reviewed

    # A second writer that still thinks the order is pending loses.
    with pytest.raises(StaleOrder):
        await repo.save(conn, OrderRecord(swapped, swapped_from=memory), "pending_review")
    assert (await repo.get(conn, order.order_id)).order.status == "verified"


async def test_list_pending_oldest_first(conn):
    repo = PostgresOrders()
    t0 = datetime(2020, 1, 1, tzinfo=UTC)
    orders = [
        _order("p2", created=t0 + timedelta(minutes=2)),
        _order("p1", created=t0 + timedelta(minutes=1)),
        _order("v", status="verified", created=t0),
    ]
    for o in orders:
        await repo.create(conn, OrderRecord(o))
    mine = [o.order_id for o in await repo.list_pending(conn) if o.order_id.startswith(RUN)]
    assert mine == [f"{RUN}_p1", f"{RUN}_p2"]
