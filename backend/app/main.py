import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.api import router
from app.contracts import ApiError, ErrorResponse
from app.core import db
from app.core.config import get_settings
from app.orders.deps import uses_database
from app.orders.rules import InvalidRequest, InvalidTransition
from app.orders.service import NotFound

log = logging.getLogger("rio")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    # Mock mode never touches the database: orders live in memory.
    if settings.database_url and not settings.use_mocks:
        await db.open_pool()
    yield
    await db.close_pool()


app = FastAPI(title="Rio", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
    """Every error leaves as ErrorResponse. Raise HTTPException(status, detail='code: message')."""
    code, _, message = str(exc.detail).partition(": ")
    body = ErrorResponse(error=ApiError(code=code, message=message or code))
    return JSONResponse(body.model_dump(), status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    where = ".".join(str(p) for p in first.get("loc", []))
    body = ErrorResponse(
        error=ApiError(code="invalid_request", message=f"{where}: {first.get('msg', 'invalid')}")
    )
    return JSONResponse(body.model_dump(), status_code=422)


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
    return _error(500, "internal_error", "something went wrong on our side")


@app.get("/api/health")
async def health() -> dict[str, object]:
    settings = get_settings()
    return {"ok": True, "mocks": settings.use_mocks, "database": uses_database()}


app.include_router(router)
