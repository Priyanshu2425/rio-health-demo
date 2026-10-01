"""The demo's email wall: record who opened it."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response

from app.contracts import VisitorRequest
from app.orders.deps import get_conn

router = APIRouter()
Conn = Annotated[Any, Depends(get_conn)]
log = logging.getLogger("rio.visitors")

UPSERT = """
INSERT INTO visitors (email) VALUES (%s)
ON CONFLICT (email) DO UPDATE SET last_seen = now(), visits = visitors.visits + 1
"""


@router.post("/visitors", status_code=204)
async def register_visitor(body: VisitorRequest, conn: Conn) -> Response:
    email = body.email.strip().lower()
    if conn is None:  # mock mode has no database
        log.info("visitor (mock mode, not stored): %s", email)
    else:
        await conn.execute(UPSERT, (email,))
    return Response(status_code=204)
