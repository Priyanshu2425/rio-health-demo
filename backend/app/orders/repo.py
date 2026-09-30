"""Order storage behind one small interface.

`PostgresOrders` reads and writes the `orders` table from 001_init.sql and is the only
store in real mode. `MemoryOrders` is for mock mode (RIO_USE_MOCKS=1, development) only;
real mode never falls back to it. Both take the connection per
call (MemoryOrders ignores it). An order is read and written whole.

Customer generic swaps are remembered as `swapped_from` (item_id -> brand SKU) so a
swap can be undone. In Postgres they ride along inside the items jsonb under a
`_swapped_from` key on each item, which the CartItem model ignores on the way out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from psycopg.types.json import Jsonb

from app.contracts import SKU, CartItem, Order, OrderStatus, ParsedRx


class StaleOrder(Exception):
    """The order changed status underneath us; the API answers 409."""


@dataclass
class OrderRecord:
    order: Order
    image: bytes | None = None
    image_mime: str | None = None
    swapped_from: dict[str, SKU] = field(default_factory=dict)


class OrderRepo(Protocol):
    async def create(self, conn: Any, record: OrderRecord) -> None: ...

    async def get(self, conn: Any, order_id: str) -> OrderRecord | None:
        """Without image bytes; use get_image for those."""

    async def get_image(self, conn: Any, order_id: str) -> tuple[bytes, str] | None: ...

    async def save(self, conn: Any, record: OrderRecord, expected_status: OrderStatus) -> None:
        """Write status, items, totals and review fields. Raises StaleOrder if the stored
        status is no longer `expected_status`."""

    async def list_pending(self, conn: Any) -> list[Order]: ...


class MemoryOrders:
    def __init__(self) -> None:
        self._rows: dict[str, OrderRecord] = {}

    def clear(self) -> None:
        self._rows.clear()

    async def create(self, conn: Any, record: OrderRecord) -> None:
        self._rows[record.order.order_id] = record

    async def get(self, conn: Any, order_id: str) -> OrderRecord | None:
        row = self._rows.get(order_id)
        if row is None:
            return None
        return OrderRecord(row.order, None, None, dict(row.swapped_from))

    async def get_image(self, conn: Any, order_id: str) -> tuple[bytes, str] | None:
        row = self._rows.get(order_id)
        if row is None or row.image is None:
            return None
        return row.image, row.image_mime or "application/octet-stream"

    async def save(self, conn: Any, record: OrderRecord, expected_status: OrderStatus) -> None:
        row = self._rows.get(record.order.order_id)
        if row is None or row.order.status != expected_status:
            raise StaleOrder(record.order.order_id)
        row.order = record.order
        row.swapped_from = dict(record.swapped_from)

    async def list_pending(self, conn: Any) -> list[Order]:
        return [r.order for r in self._rows.values() if r.order.status == "pending_review"]


_COLUMNS = (
    "order_id, created_at, source, status, (image IS NOT NULL) AS has_image, parsed_rx, items, "
    "total_inr, requires_review, pharmacist_note, reviewed_at"
)


def _items_json(record: OrderRecord) -> list[dict[str, Any]]:
    out = []
    for item in record.order.items:
        data = item.model_dump(mode="json")
        brand = record.swapped_from.get(item.item_id)
        if brand is not None:
            data["_swapped_from"] = brand.model_dump(mode="json")
        out.append(data)
    return out


def _from_row(row: dict[str, Any]) -> OrderRecord:
    swapped: dict[str, SKU] = {}
    items = []
    for data in row["items"]:
        brand = data.pop("_swapped_from", None)
        item = CartItem.model_validate(data)
        if brand is not None:
            swapped[item.item_id] = SKU.model_validate(brand)
        items.append(item)
    order = Order(
        order_id=row["order_id"],
        created_at=row["created_at"],
        source=row["source"],
        status=row["status"],
        has_image=row["has_image"],
        parsed_rx=ParsedRx.model_validate(row["parsed_rx"]) if row["parsed_rx"] else None,
        items=items,
        total_inr=float(row["total_inr"]),
        requires_review=row["requires_review"],
        pharmacist_note=row["pharmacist_note"],
        reviewed_at=row["reviewed_at"],
    )
    return OrderRecord(order, swapped_from=swapped)


class PostgresOrders:
    """Expects a psycopg AsyncConnection with row_factory=dict_row (see app.core.db)."""

    async def create(self, conn: Any, record: OrderRecord) -> None:
        o = record.order
        await conn.execute(
            "INSERT INTO orders (order_id, created_at, source, status, image, image_mime, parsed_rx, "
            "items, total_inr, requires_review, pharmacist_note, reviewed_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                o.order_id,
                o.created_at,
                o.source,
                o.status,
                record.image,
                record.image_mime,
                Jsonb(o.parsed_rx.model_dump(mode="json")) if o.parsed_rx else None,
                Jsonb(_items_json(record)),
                o.total_inr,
                o.requires_review,
                o.pharmacist_note,
                o.reviewed_at,
            ),
        )
        await conn.commit()

    async def get(self, conn: Any, order_id: str) -> OrderRecord | None:
        cur = await conn.execute(f"SELECT {_COLUMNS} FROM orders WHERE order_id = %s", (order_id,))
        row = await cur.fetchone()
        return _from_row(row) if row else None

    async def get_image(self, conn: Any, order_id: str) -> tuple[bytes, str] | None:
        cur = await conn.execute("SELECT image, image_mime FROM orders WHERE order_id = %s", (order_id,))
        row = await cur.fetchone()
        if not row or row["image"] is None:
            return None
        return bytes(row["image"]), row["image_mime"] or "application/octet-stream"

    async def save(self, conn: Any, record: OrderRecord, expected_status: OrderStatus) -> None:
        o = record.order
        cur = await conn.execute(
            "UPDATE orders SET status = %s, items = %s, total_inr = %s, pharmacist_note = %s, "
            "reviewed_at = %s WHERE order_id = %s AND status = %s",
            (
                o.status,
                Jsonb(_items_json(record)),
                o.total_inr,
                o.pharmacist_note,
                o.reviewed_at,
                o.order_id,
                expected_status,
            ),
        )
        await conn.commit()
        if cur.rowcount != 1:
            raise StaleOrder(o.order_id)

    async def list_pending(self, conn: Any) -> list[Order]:
        cur = await conn.execute(
            f"SELECT {_COLUMNS} FROM orders WHERE status = 'pending_review' ORDER BY created_at"
        )
        return [_from_row(row).order for row in await cur.fetchall()]


memory_orders = MemoryOrders()
postgres_orders = PostgresOrders()
