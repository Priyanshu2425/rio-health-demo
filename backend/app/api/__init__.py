"""HTTP routes. Owned by `feat/backend-api`; see contracts/API.md for the surface."""

from fastapi import APIRouter

from app.api import orders, pharmacist

router = APIRouter(prefix="/api")
router.include_router(orders.router)
router.include_router(pharmacist.router)
