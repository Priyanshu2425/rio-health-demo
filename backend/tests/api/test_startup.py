"""Real mode refuses to start without the database; there is no in-memory fallback."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.orders import deps


def test_real_mode_without_database_url_fails_startup(mock_mode):
    mock_mode.use_mocks = False
    with pytest.raises(RuntimeError, match="RIO_HEALTH_DATABASE_URL"), TestClient(app):
        pass
    assert deps.uses_database() is False


def test_real_mode_orders_never_fall_back_to_memory(mock_mode):
    mock_mode.use_mocks = False
    with pytest.raises(RuntimeError, match="pool is not open"):
        deps.orders()


def test_mock_mode_uses_memory(mock_mode):
    assert deps.orders() is deps.memory_orders
    assert deps.uses_database() is False
