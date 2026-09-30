"""Customer-side routes: create, poll, swap, place; samples."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, File, Request, Response, UploadFile

from app.api.guards import check_parse_rate, error, read_image
from app.contracts import Order, Sample, SwapRequest, TextOrderRequest
from app.core.config import get_settings
from app.core.llm import LLMError
from app.orders import messages, service
from app.orders.deps import get_conn, modules, orders
from app.parser.extract import UnsupportedImage

router = APIRouter()
Conn = Annotated[Any, Depends(get_conn)]

# Headroom over one vision call for matching and re-rank calls.
PIPELINE_SLACK_S = 30.0


def _parser_error(exc: BaseException) -> Exception:
    if isinstance(exc, TimeoutError) or isinstance(exc.__cause__, httpx.TimeoutException):
        return error(504, "parser_timeout", messages.PARSER_TIMEOUT)
    return error(502, "parser_failed", messages.PARSER_FAILED)


@router.post("/orders/prescription", response_model=Order)
async def create_from_prescription(
    request: Request, image: Annotated[UploadFile, File()], conn: Conn
) -> Order:
    data, mime = await read_image(request, image)
    check_parse_rate(request)  # after the image checks, so a 400 / 413 costs no upload
    mods = modules()
    budget = get_settings().openrouter_timeout_s + PIPELINE_SLACK_S
    try:
        async with asyncio.timeout(budget):
            parsed = await mods.parser.parse_prescription(data, mime)
            return await service.create_rx_order(mods, conn, "prescription", parsed, data, mime)
    except UnsupportedImage as exc:
        raise error(400, "unsupported_image", messages.UNREADABLE_IMAGE) from exc
    except (LLMError, TimeoutError) as exc:
        raise _parser_error(exc) from exc


@router.post("/orders/sample/{sample_id}", response_model=Order)
async def create_from_sample(sample_id: str, conn: Conn) -> Order:
    mods = modules()
    try:
        data, mime, parsed = await mods.parser.load_sample(conn, sample_id)
    except KeyError as exc:
        raise error(404, "not_found", messages.SAMPLE_NOT_FOUND) from exc
    try:
        return await service.create_rx_order(mods, conn, "sample", parsed, data, mime)
    except LLMError as exc:  # a re-rank call can still fail
        raise _parser_error(exc) from exc


@router.post("/orders/text", response_model=Order)
async def create_from_text(body: TextOrderRequest, conn: Conn) -> Order:
    try:
        return await service.create_text_order(modules(), conn, body.text)
    except LLMError as exc:
        raise _parser_error(exc) from exc


@router.get("/orders/{order_id}", response_model=Order)
async def get_order(order_id: str, conn: Conn) -> Order:
    return (await service.get_record(conn, order_id)).order


@router.get("/orders/{order_id}/image")
async def get_order_image(order_id: str, conn: Conn) -> Response:
    found = await orders().get_image(conn, order_id)
    if found is None:
        raise error(404, "not_found", messages.ORDER_IMAGE_NOT_FOUND)
    data, mime = found
    return Response(data, media_type=mime, headers={"Cache-Control": "private, max-age=3600"})


@router.post("/orders/{order_id}/swap", response_model=Order)
async def swap_generic(order_id: str, body: SwapRequest, conn: Conn) -> Order:
    return await service.swap(conn, order_id, body)


@router.post("/orders/{order_id}/place", response_model=Order)
async def place_order(order_id: str, conn: Conn) -> Order:
    return await service.place(conn, order_id)


@router.get("/samples", response_model=list[Sample])
async def list_samples(conn: Conn) -> list[Sample]:
    return await modules().parser.list_samples(conn)


@router.get("/samples/{sample_id}/image")
async def sample_image(sample_id: str, conn: Conn) -> Response:
    try:
        data, mime, _ = await modules().parser.load_sample(conn, sample_id)
    except KeyError as exc:
        raise error(404, "not_found", messages.SAMPLE_NOT_FOUND) from exc
    return Response(data, media_type=mime, headers={"Cache-Control": "public, max-age=86400"})
