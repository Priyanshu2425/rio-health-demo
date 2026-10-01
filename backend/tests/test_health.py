from fastapi.testclient import TestClient

from app.main import app


def test_health():
    with TestClient(app) as client:
        resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_errors_use_error_response_shape():
    with TestClient(app) as client:
        resp = client.get("/api/does-not-exist")
    assert resp.status_code == 404
    assert set(resp.json()["error"]) == {"code", "message"}


def test_pool_checks_connections_before_use(monkeypatch):
    """Neon kills idle connections; the pool must check each one before handing it out."""
    import asyncio

    from psycopg_pool import AsyncConnectionPool

    from app.core import db

    captured = {}

    class FakePool:
        check_connection = AsyncConnectionPool.check_connection

        def __init__(self, *args, **kwargs):
            captured.update(kwargs)

        async def open(self):
            pass

    monkeypatch.setattr(db, "AsyncConnectionPool", FakePool)
    monkeypatch.setattr(db, "get_settings", lambda: type("S", (), {"database_url": "postgresql://x"})())
    asyncio.run(db.open_pool())
    db._pool = None
    assert captured["check"] is AsyncConnectionPool.check_connection
    assert captured["max_idle"] <= 240
