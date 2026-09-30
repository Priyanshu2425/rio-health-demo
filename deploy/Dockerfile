# syntax=docker/dockerfile:1
#
# Build context: repo root.
#   docker build -f deploy/Dockerfile -t rio-api .
#
# Single-stage image using the official uv image, following the "uv sync --frozen
# --no-install-project" layer-caching pattern: dependencies are installed from
# pyproject.toml + uv.lock before the rest of the code is copied in, so editing
# app code doesn't invalidate the dependency layer.

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app/backend

# 1. Install dependencies only, using just the lock files, so this layer is
#    cached as long as dependencies don't change.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 2. Copy the rest of the repo needed at runtime, keeping the repo-relative
#    layout so app.orders.mocks can find contracts/fixtures three parents up
#    from backend/app/orders/mocks.py (i.e. /app/contracts/fixtures).
WORKDIR /app
COPY backend/ backend/
COPY contracts/ contracts/
COPY data/ data/

# Install the project itself now that its code is present.
WORKDIR /app/backend
RUN uv sync --frozen --no-dev

# Create a non-root user and hand it the app directory.
RUN groupadd --system rio && useradd --system --gid rio --home /app rio \
    && chown -R rio:rio /app
USER rio

ENV PATH="/app/backend/.venv/bin:${PATH}"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; \
    sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2).status == 200 else 1)" \
    || exit 1

# Single worker is required: the app uses an in-memory rate limiter that is
# only correct with one process.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", "--workers", "1", \
     "--proxy-headers", "--forwarded-allow-ips=*"]
