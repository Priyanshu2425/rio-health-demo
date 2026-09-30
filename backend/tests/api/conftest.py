"""API tests run in mock mode with no database, whatever the local .env says."""

import pytest
from fastapi.testclient import TestClient

from app.api.guards import parse_limiter
from app.core.config import get_settings
from app.main import app
from app.orders.repo import memory_orders


@pytest.fixture(autouse=True)
def mock_mode(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "use_mocks", True)
    monkeypatch.setattr(settings, "database_url", None)
    monkeypatch.setattr(settings, "parse_rate_limit_per_hour", 10)
    monkeypatch.setattr(settings, "max_upload_mb", 5)
    memory_orders.clear()
    parse_limiter.reset()
    yield settings
    memory_orders.clear()
    parse_limiter.reset()


@pytest.fixture
def client(mock_mode):
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
