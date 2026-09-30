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


# ---------------------------------------------------------------------------
# Startup forecast bootstrap (no database: the connection is faked)
# ---------------------------------------------------------------------------


class _FakeConn:
    def __init__(self, has_run: bool) -> None:
        self.has_run = has_run

    async def execute(self, sql):
        conn = self

        class _Cur:
            async def fetchone(self):
                return {"has_run": conn.has_run}

        return _Cur()

    async def commit(self):
        pass


def _fake_db(monkeypatch, has_run: bool, run):
    from app.orders import startup

    async def get_conn():
        yield _FakeConn(has_run)

    monkeypatch.setattr(startup.db, "get_conn", get_conn)
    monkeypatch.setattr(startup.forecast, "run", run)
    return startup


async def test_forecast_runs_when_table_is_empty(monkeypatch):
    calls = []

    async def run(conn):
        calls.append(conn)
        return type("S", (), {"reorders": []})()

    startup = _fake_db(monkeypatch, has_run=False, run=run)
    await startup.start_forecast_task()
    assert len(calls) == 1


async def test_forecast_skipped_when_a_run_exists(monkeypatch):
    calls = []

    async def run(conn):
        calls.append(conn)

    startup = _fake_db(monkeypatch, has_run=True, run=run)
    await startup.ensure_forecast()
    assert calls == []


async def test_forecast_failure_does_not_raise(monkeypatch, caplog):
    async def run(conn):
        raise RuntimeError("boom")

    startup = _fake_db(monkeypatch, has_run=False, run=run)
    await startup.ensure_forecast()
    assert "startup forecast run failed" in caplog.text
