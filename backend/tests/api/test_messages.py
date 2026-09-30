"""Error messages are shown verbatim in the UI: plain sentences, no internal ids."""

import re

import pytest

from app.contracts import ErrorResponse
from app.core.llm import LLMError
from app.orders import messages, mocks
from tests.api.test_routes import BROKEN_JPEG, PNG, upload

INTERNAL = re.compile(r"itm_\d|sku_|ord_|_id\b|\bbody\.|pending_review|confirmed_otc|needs_prescription|;")


def assert_readable(resp, status, code):
    assert resp.status_code == status, resp.text
    e = ErrorResponse.model_validate(resp.json()).error
    assert e.code == code
    m = e.message
    assert m[0].isupper(), m
    assert m.endswith("."), m
    assert not INTERNAL.search(m), m
    assert 1 <= len(re.findall(r"[.!?](?:\s|$)", m)) <= 2, m
    return m


def _sample(client):
    return client.post("/api/orders/sample/typed_clinic_3").json()


def test_404s(client):
    assert_readable(client.get("/api/orders/ord_nope"), 404, "not_found")
    assert_readable(client.get("/api/orders/ord_nope/image"), 404, "not_found")
    assert_readable(client.post("/api/orders/sample/nope"), 404, "not_found")
    assert_readable(client.get("/api/samples/nope/image"), 404, "not_found")
    assert_readable(client.get("/api/forecast/sku/sku_nope"), 404, "not_found")
    assert_readable(client.get("/api/no-such-route"), 404, "not_found")


def test_404_no_forecast(client, monkeypatch):
    async def none(conn):
        raise LookupError

    monkeypatch.setattr(mocks.forecast, "get_summary", staticmethod(none))
    assert_readable(client.get("/api/forecast/summary"), 404, "no_forecast")


def test_409s(client):
    order = _sample(client)["order_id"]
    m = assert_readable(client.post(f"/api/orders/{order}/place"), 409, "invalid_transition")
    assert "still checking" in m
    client.post(f"/api/queue/{order}/review", json={"decision": "reject"})
    m = assert_readable(
        client.post(f"/api/queue/{order}/review", json={"decision": "approve"}), 409, "invalid_transition"
    )
    assert m == "This order was already reviewed, so it can't be changed now."
    assert_readable(
        client.post(f"/api/orders/{order}/swap", json={"item_id": "itm_1", "use_generic": True}),
        409,
        "invalid_transition",
    )
    assert_readable(client.post(f"/api/orders/{order}/place"), 409, "invalid_transition")

    rx = client.post("/api/orders/text", json={"text": "augmentin"}).json()["order_id"]
    m = assert_readable(client.post(f"/api/orders/{rx}/place"), 409, "invalid_transition")
    assert "prescription" in m


def test_422_review(client):
    order = _sample(client)["order_id"]
    url = f"/api/queue/{order}/review"
    cases = [
        {"decision": "maybe"},
        {"decision": "approve", "items": [{"item_id": "itm_3", "action": "edit", "sku_id": "sku_nope"}]},
        {"decision": "approve", "items": [{"item_id": "itm_3", "action": "edit"}]},
        {"decision": "approve", "items": [{"item_id": "itm_9", "action": "remove"}]},
        {"decision": "approve", "items": [{"item_id": "itm_3", "action": "edit", "quantity_packs": 0}]},
        {
            "decision": "approve",
            "items": [{"item_id": "itm_3", "action": "remove"}, {"item_id": "itm_3", "action": "remove"}],
        },
    ]
    for case in cases:
        assert_readable(client.post(url, json=case), 422, "invalid_request")
    m = assert_readable(
        client.post(url, json={"decision": "approve", "items": [{"item_id": "itm_3", "action": "edit"}]}),
        422,
        "invalid_request",
    )
    assert m == "Please choose a new product or quantity for Dolo 650, or approve it as it is."


def test_422_swap_and_text(client):
    order = _sample(client)["order_id"]
    m = assert_readable(
        client.post(f"/api/orders/{order}/swap", json={"item_id": "itm_2", "use_generic": True}),
        422,
        "invalid_request",
    )
    assert "Pan 40" in m
    m = assert_readable(client.post("/api/orders/text", json={"text": "flubberwort"}), 422, "invalid_request")
    assert m == "We couldn't find “flubberwort” in our catalog. Try the brand name printed on the strip."
    assert_readable(client.post("/api/orders/text", json={"text": ""}), 422, "invalid_request")
    assert_readable(client.post("/api/orders/text", content=b"not json"), 422, "invalid_request")
    assert_readable(
        client.get("/api/catalog/search", params={"q": "dolo", "limit": 50}), 422, "invalid_request"
    )
    assert_readable(client.post("/api/orders/prescription"), 422, "invalid_request")


def test_400_413_429(client, mock_mode):
    assert_readable(upload(client, b"%PDF-1.7", "application/pdf"), 400, "unsupported_image")
    assert_readable(upload(client, BROKEN_JPEG, "image/jpeg"), 400, "unsupported_image")
    mock_mode.max_upload_mb = 1
    m = assert_readable(upload(client, PNG + b"\x00" * (1024 * 1024)), 413, "image_too_large")
    assert "1 MB" in m
    mock_mode.parse_rate_limit_per_hour = 1
    upload(client)
    m = assert_readable(upload(client), 429, "rate_limited")
    assert re.fullmatch(r".*try again in (\d+) minutes?,.*", m), "the frontend parses the minutes"
    assert len(re.findall(r"\d+", m)) == 1, "the minutes are the only number"


def test_rate_limited_wording():
    assert "in 1 minute," in messages.rate_limited(1)
    assert "in 42 minutes," in messages.rate_limited(42)


def test_502_504_500(client, monkeypatch):
    async def junk(image, mime):
        raise LLMError("junk")

    monkeypatch.setattr(mocks.parser, "parse_prescription", staticmethod(junk))
    assert_readable(upload(client), 502, "parser_failed")

    async def slow(image, mime):
        raise TimeoutError

    monkeypatch.setattr(mocks.parser, "parse_prescription", staticmethod(slow))
    assert_readable(upload(client), 504, "parser_timeout")

    async def bug(image, mime):
        raise ValueError("internal detail")

    monkeypatch.setattr(mocks.parser, "parse_prescription", staticmethod(bug))
    assert_readable(upload(client), 500, "internal_error")


def test_stale_order_message_is_readable():
    assert messages.STALE_ORDER == "Someone else just updated this order. Please refresh and try again."


@pytest.mark.parametrize(
    "current", ["pending_review", "verified", "rejected", "confirmed_otc", "needs_prescription", "placed"]
)
@pytest.mark.parametrize("target", ["verified", "rejected", "placed"])
def test_every_transition_message_is_a_sentence(current, target):
    m = messages.invalid_transition(current, target)
    assert m[0].isupper() and m.endswith(".") and not INTERNAL.search(m)
