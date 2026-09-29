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
