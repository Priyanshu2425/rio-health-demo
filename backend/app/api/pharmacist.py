"""Pharmacist routes (queue, review, SKU search) and forecast."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.api.guards import error
from app.contracts import ForecastSummary, MatchCandidate, Order, QueueItem, ReviewRequest, SkuForecast
from app.orders import messages, service
from app.orders.deps import get_conn, modules

router = APIRouter()
Conn = Annotated[Any, Depends(get_conn)]


@router.get("/queue", response_model=list[QueueItem])
async def get_queue(conn: Conn) -> list[QueueItem]:
    return await service.queue(conn)


@router.post("/queue/{order_id}/review", response_model=Order)
async def review_order(order_id: str, body: ReviewRequest, conn: Conn) -> Order:
    return await service.review(modules(), conn, order_id, body)


@router.get("/catalog/search", response_model=list[MatchCandidate])
async def catalog_search(
    conn: Conn,
    q: Annotated[str, Query(min_length=1, max_length=100)],
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> list[MatchCandidate]:
    return await modules().catalog.search(conn, q, limit)


@router.get("/forecast/summary", response_model=ForecastSummary)
async def forecast_summary(conn: Conn) -> ForecastSummary:
    try:
        return await modules().forecast.get_summary(conn)
    except LookupError as exc:
        raise error(404, "no_forecast", messages.NO_FORECAST) from exc


@router.get("/forecast/sku/{sku_id}", response_model=SkuForecast)
async def forecast_sku(sku_id: str, conn: Conn, area: str | None = None) -> SkuForecast:
    fc = modules().forecast
    if area is None:
        try:
            area = (await fc.get_summary(conn)).areas[0]
        except (LookupError, IndexError) as exc:
            raise error(404, "no_forecast", messages.NO_FORECAST) from exc
    found = await fc.get_sku_forecast(conn, sku_id, area)
    if found is None:
        raise error(404, "not_found", messages.SKU_FORECAST_NOT_FOUND)
    return found
