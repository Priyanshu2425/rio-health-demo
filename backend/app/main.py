import asyncio
import logging
import re
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.api import router
from app.contracts import ApiError, ErrorResponse
from app.core.config import get_settings
from app.orders import messages, startup
from app.orders.deps import uses_database
from app.orders.rules import InvalidRequest, InvalidTransition
from app.orders.service import NotFound

log = logging.getLogger("rio")
_CODE = re.compile(r"[a-z_]+")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    if settings.use_mocks:
        # Development only: fixtures and in-memory orders, never the database.
        yield
        return
    await startup.open_database(settings)
    forecast_task = startup.start_forecast_task()
    try:
        yield
    finally:
        forecast_task.cancel()
        with suppress(asyncio.CancelledError):
            await forecast_task
        await startup.close_database()


app = FastAPI(title="Rio", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def no_store_by_default(request: Request, call_next):
    """API data changes on every request (orders, the queue), so no cache may keep it.

    The buildspacelabs.com zone caches responses that carry no Cache-Control, which served
    a stale pharmacist queue and order status. Routes that are safe to cache (sample
    images) set their own header.
    """
    response = await call_next(request)
    response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
    """Every error leaves as ErrorResponse. Raise HTTPException(status, detail='code: message').

    Framework errors (an unknown path, a wrong method) carry plain details like
    'Not Found'; they get a contract code and a readable message instead.
    """
    code, sep, message = str(exc.detail).partition(": ")
    if not (sep and _CODE.fullmatch(code)):
        if exc.status_code == 404:
            code, message = "not_found", messages.PAGE_NOT_FOUND
        else:
            code, message = "invalid_request", messages.REQUEST_FAILED
    return _error(exc.status_code, code, message)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    """422 with a message about the first bad field, in words a person can act on."""
    first = exc.errors()[0] if exc.errors() else {}
    fields = [str(p) for p in first.get("loc", []) if isinstance(p, str)]
    message = next((messages.INVALID_FIELD[f] for f in reversed(fields) if f in messages.INVALID_FIELD), None)
    return _error(422, "invalid_request", message or messages.INVALID_REQUEST)


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        ErrorResponse(error=ApiError(code=code, message=message)).model_dump(), status_code=status
    )


@app.exception_handler(NotFound)
async def not_found(_: Request, exc: NotFound) -> JSONResponse:
    return _error(404, "not_found", str(exc))


@app.exception_handler(InvalidTransition)
async def invalid_transition(_: Request, exc: InvalidTransition) -> JSONResponse:
    return _error(409, "invalid_transition", str(exc))


@app.exception_handler(InvalidRequest)
async def invalid_request(_: Request, exc: InvalidRequest) -> JSONResponse:
    return _error(422, "invalid_request", str(exc))


@app.exception_handler(Exception)
async def unexpected(request: Request, exc: Exception) -> JSONResponse:
    """Last resort: log it, never leak a stack trace to the client."""
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return _error(500, "internal_error", messages.INTERNAL_ERROR)


@app.get("/api/health")
async def health() -> dict[str, object]:
    settings = get_settings()
    return {"ok": True, "mocks": settings.use_mocks, "database": uses_database()}


app.include_router(router)
