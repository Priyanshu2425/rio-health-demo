"""The email wall, in mock mode (no database)."""

import pytest


@pytest.mark.parametrize("email", ["a@b.co", "Priya.S+demo@Example.in", " name@clinic.org "])
def test_accepts_plausible_emails(client, email):
    resp = client.post("/api/visitors", json={"email": email.strip()})
    assert resp.status_code == 204
    assert resp.content == b""


@pytest.mark.parametrize("email", ["", "no-at-sign", "a@b", "two@@b.co", "spa ce@b.co"])
def test_rejects_malformed_emails_with_a_plain_message(client, email):
    resp = client.post("/api/visitors", json={"email": email})
    assert resp.status_code == 422
    err = resp.json()["error"]
    assert err["code"] == "invalid_request"
    assert "valid email" in err["message"]
