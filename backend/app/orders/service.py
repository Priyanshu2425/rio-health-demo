"""Order flows: glue between the modules, the pure rules and storage."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any

from app.contracts import (
    SKU,
    CartItem,
    MatchResult,
    Order,
    OrderSource,
    ParsedRx,
    QueueItem,
    ReviewRequest,
    SwapRequest,
)
from app.orders import messages, rules
from app.orders.deps import Modules, orders
from app.orders.repo import OrderRecord, StaleOrder


class NotFound(Exception):
    """404 not_found."""


def new_order_id() -> str:
    return f"ord_{secrets.token_hex(6)}"


def now() -> datetime:
    return datetime.now(UTC)


async def _generic(mods: Modules, conn: Any, sku: SKU | None) -> SKU | None:
    return await mods.catalog.cheapest_generic(conn, sku) if sku is not None else None


async def build_cart(mods: Modules, conn: Any, source: ParsedRx | str) -> list[CartItem]:
    """ParsedRx -> one item per prescription line; str -> one item per typed request."""
    if isinstance(source, ParsedRx):
        matches: list[MatchResult] = []
        for line in source.lines:  # sequential: the lines share one connection
            matches.append(await mods.parser.match_line(conn, line))
        generics = [await _generic(mods, conn, m.sku) for m in matches]
        return [
            rules.make_item(f"itm_{i}", m, g, line=line)
            for i, (line, m, g) in enumerate(zip(source.lines, matches, generics, strict=True), 1)
        ]
    pairs = await mods.parser.match_text(conn, source)
    generics = [await _generic(mods, conn, m.sku) for _, m in pairs]
    return [
        rules.make_item(f"itm_{i}", m, g, requested_text=text)
        for i, ((text, m), g) in enumerate(zip(pairs, generics, strict=True), 1)
    ]


async def create_rx_order(
    mods: Modules, conn: Any, source: OrderSource, parsed: ParsedRx, image: bytes, mime: str
) -> Order:
    items = await build_cart(mods, conn, parsed)
    order = Order(
        order_id=new_order_id(),
        created_at=now(),
        source=source,
        status="pending_review",
        has_image=True,
        parsed_rx=parsed,
        items=items,
        total_inr=rules.order_total(items),
        requires_review=True,
    )
    await orders().create(conn, OrderRecord(order, image, mime))
    return order


async def create_text_order(mods: Modules, conn: Any, text: str) -> Order:
    items = await build_cart(mods, conn, text)
    if not any(i.sku is not None for i in items):
        raise rules.InvalidRequest(messages.nothing_matched(i.requested_text or "" for i in items))
    status = rules.text_order_status(items)
    if status == "confirmed_otc":
        # Nothing to review: matched items are in, unmatched ones are dropped.
        items = [i.model_copy(update={"status": "approved" if i.sku else "removed"}) for i in items]
    order = Order(
        order_id=new_order_id(),
        created_at=now(),
        source="text",
        status=status,
        has_image=False,
        items=items,
        total_inr=rules.order_total(items),
        requires_review=False,
    )
    await orders().create(conn, OrderRecord(order))
    return order


async def get_record(conn: Any, order_id: str) -> OrderRecord:
    record = await orders().get(conn, order_id)
    if record is None:
        raise NotFound(messages.ORDER_NOT_FOUND)
    return record


async def _save(conn: Any, record: OrderRecord, expected: str) -> Order:
    try:
        await orders().save(conn, record, expected)  # type: ignore[arg-type]
    except StaleOrder as exc:
        raise rules.InvalidTransition(messages.STALE_ORDER) from exc
    return record.order


async def swap(conn: Any, order_id: str, req: SwapRequest) -> Order:
    record = await get_record(conn, order_id)
    before = record.order.status
    order, swapped = rules.apply_swap(record.order, req, record.swapped_from)
    return await _save(conn, OrderRecord(order, swapped_from=swapped), before)


async def place(conn: Any, order_id: str) -> Order:
    record = await get_record(conn, order_id)
    before = record.order.status
    rules.check_transition(before, "placed")
    order = record.order.model_copy(update={"status": "placed"})
    return await _save(conn, OrderRecord(order, swapped_from=record.swapped_from), before)


async def review(mods: Modules, conn: Any, order_id: str, req: ReviewRequest) -> Order:
    record = await get_record(conn, order_id)
    before = record.order.status
    # apply_review owns the transition check; only look SKUs up for a reviewable order.
    ids = sorted(rules.edit_sku_ids(req)) if before == "pending_review" else []
    skus = {i: await mods.catalog.get_sku(conn, i) for i in ids}
    generics = {i: await _generic(mods, conn, s) for i, s in skus.items()}
    order = rules.apply_review(record.order, req, skus, generics, now(), record.swapped_from)
    # An edited SKU replaces whatever the customer swapped to.
    swapped = {
        k: v
        for k, v in record.swapped_from.items()
        if not any(d.item_id == k and d.action == "edit" and d.sku_id for d in req.items)
    }
    return await _save(conn, OrderRecord(order, swapped_from=swapped), before)


async def queue(conn: Any) -> list[QueueItem]:
    return rules.build_queue(await orders().list_pending(conn))
