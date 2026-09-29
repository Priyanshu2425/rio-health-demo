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


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    if settings.database_url:
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


@app.get("/api/health")
async def health() -> dict[str, object]:
    settings = get_settings()
    return {"ok": True, "mocks": settings.use_mocks, "database": settings.database_url is not None}


app.include_router(router)
