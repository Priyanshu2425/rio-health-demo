"""Every route in contracts/API.md, end to end against the mock layer."""

import io

import pytest
from PIL import Image
from pydantic import TypeAdapter

from app import contracts as c
from app.orders import mocks

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 64


def ok(resp, shape=c.Order):
    assert resp.status_code == 200, resp.text
    return TypeAdapter(shape).validate_python(resp.json())


def err(resp, status, code):
    assert resp.status_code == status, resp.text
    body = c.ErrorResponse.model_validate(resp.json())
    assert body.error.code == code
    return body.error


def upload(client, data=PNG, mime="image/png", headers=None):
    return client.post(
        "/api/orders/prescription", files={"image": ("rx.png", data, mime)}, headers=headers or {}
    )


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


def test_health_reports_mock_mode(client):
    assert client.get("/api/health").json() == {"ok": True, "mocks": True, "database": False}


# ---------------------------------------------------------------------------
# Samples and sample orders
# ---------------------------------------------------------------------------


def test_samples_list_and_images(client):
    samples = ok(client.get("/api/samples"), list[c.Sample])
    assert [s.sample_id for s in samples] == ["typed_clinic_3", "handwritten_2"]
    for s in samples:
        resp = client.get(s.thumbnail_url)
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        Image.open(io.BytesIO(resp.content)).verify()


def test_unknown_sample(client):
    err(client.get("/api/samples/nope/image"), 404, "not_found")
    err(client.post("/api/orders/sample/nope"), 404, "not_found")


def test_sample_order_matches_fixture_triage(client):
    order = ok(client.post("/api/orders/sample/typed_clinic_3"))
    assert order.status == "pending_review"
    assert order.source == "sample"
    assert order.requires_review is True
    assert order.has_image is True
    assert [i.confidence.triage for i in order.items] == ["green", "amber", "red"]
    assert [i.sku.sku_id for i in order.items] == ["sku_augmentin_625", "sku_pan_40", "sku_dolo_650"]
    assert order.items[0].generic_alternative.sku_id == "sku_moxclav_625"
    assert order.total_inr == 412.1
    assert all(r for i in order.items if i.confidence.triage != "green" for r in [i.confidence.reasons])

    image = client.get(f"/api/orders/{order.order_id}/image")
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"
    assert ok(client.get(f"/api/orders/{order.order_id}")) == order


def test_handwritten_sample_has_two_lines(client):
    order = ok(client.post("/api/orders/sample/handwritten_2"))
    assert len(order.items) == 2


# ---------------------------------------------------------------------------
# Prescription upload
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("data,mime", [(PNG, "image/png"), (JPEG, "image/jpeg"), (WEBP, "image/webp")])
def test_upload_accepts_real_images(client, data, mime):
    order = ok(upload(client, data, mime))
    assert order.source == "prescription"
    assert order.status == "pending_review"
    assert order.parsed_rx is not None and len(order.items) == 3
    image = client.get(f"/api/orders/{order.order_id}/image")
    assert image.content == data
    assert image.headers["content-type"] == mime


def test_upload_trusts_magic_bytes_over_declared_type(client):
    order = ok(upload(client, JPEG, "application/octet-stream"))
    assert client.get(f"/api/orders/{order.order_id}/image").headers["content-type"] == "image/jpeg"


@pytest.mark.parametrize(
    "data,mime",
    [
        (b"%PDF-1.7 not an image", "application/pdf"),
        (b"%PDF-1.7 not an image", "image/png"),  # lies about its type
        (b"GIF89a" + b"\x00" * 20, "image/gif"),
        (b"", "image/png"),
    ],
)
def test_upload_rejects_non_images(client, data, mime):
    err(upload(client, data, mime), 400, "unsupported_image")


def test_upload_too_large(client, mock_mode):
    mock_mode.max_upload_mb = 1
    big = PNG + b"\x00" * (1024 * 1024)
    err(upload(client, big), 413, "image_too_large")


def test_upload_missing_file(client):
    err(client.post("/api/orders/prescription"), 422, "invalid_request")


def test_upload_rate_limited_per_ip(client, mock_mode):
    mock_mode.parse_rate_limit_per_hour = 2
    a = {"CF-Connecting-IP": "203.0.113.1"}
    b = {"CF-Connecting-IP": "203.0.113.2"}
    ok(upload(client, headers=a))
    ok(upload(client, headers=a))
    e = err(upload(client, headers=a), 429, "rate_limited")
    assert "try again in" in e.message
    ok(upload(client, headers=b))  # another IP is unaffected
    ok(client.post("/api/orders/sample/typed_clinic_3", headers=a))  # samples are not limited


def test_parser_llm_error_is_502(client, monkeypatch):
    from app.core.llm import LLMError

    async def boom(image, mime):
        raise LLMError("junk")

    monkeypatch.setattr(mocks.parser, "parse_prescription", staticmethod(boom))
    err(upload(client), 502, "parser_failed")


def test_parser_http_timeout_is_504(client, monkeypatch):
    import httpx

    from app.core.llm import LLMError

    async def slow(image, mime):
        try:
            raise httpx.ReadTimeout("slow")
        except httpx.ReadTimeout as exc:
            raise LLMError("openrouter request failed") from exc

    monkeypatch.setattr(mocks.parser, "parse_prescription", staticmethod(slow))
    err(upload(client), 504, "parser_timeout")


def test_pipeline_budget_timeout_is_504(client, monkeypatch, mock_mode):
    import asyncio

    from app.api import orders as api_orders

    async def hang(image, mime):
        await asyncio.sleep(5)

    monkeypatch.setattr(mocks.parser, "parse_prescription", staticmethod(hang))
    monkeypatch.setattr(mock_mode, "openrouter_timeout_s", 0.05)
    monkeypatch.setattr(api_orders, "PIPELINE_SLACK_S", 0.0)
    err(upload(client), 504, "parser_timeout")


def test_unexpected_error_is_500_without_stack(client, monkeypatch):
    async def bug(image, mime):
        raise ValueError("secret internals")

    monkeypatch.setattr(mocks.parser, "parse_prescription", staticmethod(bug))
    e = err(upload(client), 500, "internal_error")
    assert "secret" not in e.message


# ---------------------------------------------------------------------------
# Text orders
# ---------------------------------------------------------------------------


def test_text_otc(client):
    order = ok(client.post("/api/orders/text", json={"text": "dolo and ORS"}))
    assert order.status == "confirmed_otc"
    assert order.requires_review is False
    assert order.has_image is False
    assert [i.sku.sku_id for i in order.items] == ["sku_dolo_650", "sku_electral_21g"]
    assert [i.requested_text for i in order.items] == ["dolo", "ORS"]
    assert all(i.status == "approved" for i in order.items)
    assert order.total_inr == 55.6


def test_text_rx_needs_prescription(client):
    order = ok(client.post("/api/orders/text", json={"text": "augmentin"}))
    assert order.status == "needs_prescription"
    assert order.items[0].sku.rx_only
    err(client.post(f"/api/orders/{order.order_id}/place"), 409, "invalid_transition")


def test_text_mixed_needs_prescription(client):
    order = ok(client.post("/api/orders/text", json={"text": "dolo, azithromycin 500"}))
    assert order.status == "needs_prescription"


def test_text_counts_and_unmatched(client):
    order = ok(client.post("/api/orders/text", json={"text": "2 strips of crocin and flubberwort"}))
    assert order.status == "confirmed_otc"
    crocin, unknown = order.items
    assert crocin.quantity_packs == 2
    assert unknown.sku is None and unknown.status == "removed"
    assert order.total_inr == crocin.line_total_inr


@pytest.mark.parametrize(
    "body,status,code",
    [
        ({"text": ""}, 422, "invalid_request"),
        ({"text": "x" * 501}, 422, "invalid_request"),
        ({}, 422, "invalid_request"),
        ({"text": "flubberwort"}, 422, "invalid_request"),
    ],
)
def test_text_invalid(client, body, status, code):
    err(client.post("/api/orders/text", json=body), status, code)


def test_otc_order_places_directly(client):
    order = ok(client.post("/api/orders/text", json={"text": "dolo and ORS"}))
    placed = ok(client.post(f"/api/orders/{order.order_id}/place"))
    assert placed.status == "placed"
    err(client.post(f"/api/orders/{order.order_id}/place"), 409, "invalid_transition")


# ---------------------------------------------------------------------------
# Orders: get, image, swap, place
# ---------------------------------------------------------------------------


def test_unknown_order(client):
    err(client.get("/api/orders/ord_nope"), 404, "not_found")
    err(client.get("/api/orders/ord_nope/image"), 404, "not_found")
    err(client.post("/api/orders/ord_nope/place"), 404, "not_found")
    err(
        client.post("/api/orders/ord_nope/swap", json={"item_id": "itm_1", "use_generic": True}),
        404,
        "not_found",
    )
    err(client.post("/api/queue/ord_nope/review", json={"decision": "approve"}), 404, "not_found")


def test_text_order_has_no_image(client):
    order = ok(client.post("/api/orders/text", json={"text": "dolo"}))
    err(client.get(f"/api/orders/{order.order_id}/image"), 404, "not_found")


def test_swap_generic_and_undo(client):
    order = ok(client.post("/api/orders/sample/typed_clinic_3"))
    url = f"/api/orders/{order.order_id}/swap"
    swapped = ok(client.post(url, json={"item_id": "itm_1", "use_generic": True}))
    item = swapped.items[0]
    assert item.sku.sku_id == "sku_moxclav_625" == item.generic_alternative.sku_id
    assert item.savings_inr == 42.5
    assert swapped.total_inr == round(order.total_inr - 42.5, 2)
    assert ok(client.get(f"/api/orders/{order.order_id}")) == swapped

    undone = ok(client.post(url, json={"item_id": "itm_1", "use_generic": False}))
    assert undone.items[0].sku.sku_id == "sku_augmentin_625"
    assert undone.total_inr == order.total_inr


def test_swap_errors(client):
    order = ok(client.post("/api/orders/sample/typed_clinic_3"))
    url = f"/api/orders/{order.order_id}/swap"
    err(client.post(url, json={"item_id": "itm_2", "use_generic": True}), 422, "invalid_request")
    err(client.post(url, json={"item_id": "itm_99", "use_generic": True}), 422, "invalid_request")
    err(client.post(url, json={"item_id": "itm_1"}), 422, "invalid_request")
    ok(client.post(f"/api/queue/{order.order_id}/review", json=_approve_body()))
    err(client.post(url, json={"item_id": "itm_1", "use_generic": True}), 409, "invalid_transition")


def test_place_before_review_is_409(client):
    order = ok(client.post("/api/orders/sample/typed_clinic_3"))
    err(client.post(f"/api/orders/{order.order_id}/place"), 409, "invalid_transition")


# ---------------------------------------------------------------------------
# Pharmacist: queue and review
# ---------------------------------------------------------------------------


def _approve_body(note=None):
    # itm_3 (Dolo, red) is swapped for the SKU the pharmacist confirms; itm_2 gets 2 strips.
    return {
        "decision": "approve",
        "items": [
            {"item_id": "itm_2", "action": "edit", "quantity_packs": 2},
            {"item_id": "itm_3", "action": "edit", "sku_id": "sku_pacimol_650"},
        ],
        "note": note,
    }


def test_queue_orders_worst_first_then_oldest(client):
    first = ok(client.post("/api/orders/sample/handwritten_2"))  # has a red line
    ok(client.post("/api/orders/text", json={"text": "dolo"}))  # not in the queue
    second = ok(client.post("/api/orders/sample/typed_clinic_3"))  # also red, newer
    queue = ok(client.get("/api/queue"), list[c.QueueItem])
    assert [q.order_id for q in queue] == [first.order_id, second.order_id]
    assert queue[1].counts == {"green": 1, "amber": 1, "red": 1}
    assert queue[1].worst_triage == "red"


def test_review_flow_to_placed(client):
    order = ok(client.post("/api/orders/sample/typed_clinic_3"))
    reviewed = ok(client.post(f"/api/queue/{order.order_id}/review", json=_approve_body("checked")))
    assert reviewed.status == "verified"
    assert reviewed.reviewed_at is not None
    assert reviewed.pharmacist_note == "checked"
    items = {i.item_id: i for i in reviewed.items}
    assert items["itm_1"].status == "approved"
    assert items["itm_2"].status == "edited" and items["itm_2"].quantity_packs == 2
    assert items["itm_3"].status == "edited" and items["itm_3"].sku.sku_id == "sku_pacimol_650"
    assert reviewed.total_inr == round(223.5 + 2 * 155.0 + 28.0, 2)
    assert ok(client.get("/api/queue"), list[c.QueueItem]) == []

    err(client.post(f"/api/queue/{order.order_id}/review", json=_approve_body()), 409, "invalid_transition")
    placed = ok(client.post(f"/api/orders/{order.order_id}/place"))
    assert placed.status == "placed"


def test_review_reject(client):
    order = ok(client.post("/api/orders/sample/typed_clinic_3"))
    rejected = ok(
        client.post(f"/api/queue/{order.order_id}/review", json={"decision": "reject", "note": "blurry"})
    )
    assert rejected.status == "rejected" and rejected.pharmacist_note == "blurry"
    err(client.post(f"/api/orders/{order.order_id}/place"), 409, "invalid_transition")


@pytest.mark.parametrize(
    "body",
    [
        {"decision": "maybe"},
        {"decision": "approve", "items": [{"item_id": "itm_3", "action": "edit", "sku_id": "sku_nope"}]},
        {"decision": "approve", "items": [{"item_id": "itm_3", "action": "edit", "quantity_packs": 0}]},
        {"decision": "approve", "items": [{"item_id": "itm_9", "action": "remove"}]},
    ],
)
def test_review_invalid(client, body):
    order = ok(client.post("/api/orders/sample/typed_clinic_3"))
    err(client.post(f"/api/queue/{order.order_id}/review", json=body), 422, "invalid_request")


def test_review_text_order_is_409(client):
    order = ok(client.post("/api/orders/text", json={"text": "dolo"}))
    err(
        client.post(f"/api/queue/{order.order_id}/review", json={"decision": "approve"}),
        409,
        "invalid_transition",
    )


# ---------------------------------------------------------------------------
# Catalog search
# ---------------------------------------------------------------------------


def test_catalog_search(client):
    found = ok(
        client.get("/api/catalog/search", params={"q": "augmentin", "limit": 3}), list[c.MatchCandidate]
    )
    assert found[0].sku.sku_id == "sku_augmentin_625"
    assert len(found) <= 3
    assert [f.score for f in found] == sorted((f.score for f in found), reverse=True)


def test_catalog_search_by_composition(client):
    found = ok(
        client.get("/api/catalog/search", params={"q": "amoxicillin clavulanate 500/125"}),
        list[c.MatchCandidate],
    )
    assert {f.sku.sku_id for f in found[:2]} == {"sku_augmentin_625", "sku_moxclav_625"}


@pytest.mark.parametrize("params", [{"q": "dolo", "limit": 21}, {"q": ""}, {}, {"q": "dolo", "limit": 0}])
def test_catalog_search_invalid(client, params):
    err(client.get("/api/catalog/search", params=params), 422, "invalid_request")


# ---------------------------------------------------------------------------
# Forecast
# ---------------------------------------------------------------------------


def test_forecast_summary(client):
    summary = ok(client.get("/api/forecast/summary"), c.ForecastSummary)
    assert summary.reorders[0].stockout_risk


def test_forecast_sku(client):
    fc = ok(client.get("/api/forecast/sku/sku_pan_40", params={"area": "Area B"}), c.SkuForecast)
    assert (fc.sku_id, fc.area, fc.brand_name) == ("sku_pan_40", "Area B", "Pan 40")
    default_area = ok(client.get("/api/forecast/sku/sku_dolo_650"), c.SkuForecast)
    assert default_area.area == "Area A"


def test_forecast_unknown(client):
    err(client.get("/api/forecast/sku/sku_nope"), 404, "not_found")
    err(client.get("/api/forecast/sku/sku_dolo_650", params={"area": "Mars"}), 404, "not_found")


def test_forecast_not_run_yet(client, monkeypatch):
    async def none(conn):
        raise LookupError

    monkeypatch.setattr(mocks.forecast, "get_summary", staticmethod(none))
    err(client.get("/api/forecast/summary"), 404, "no_forecast")
    err(client.get("/api/forecast/sku/sku_dolo_650"), 404, "no_forecast")


# ---------------------------------------------------------------------------
# Wave 2 review fixes
# ---------------------------------------------------------------------------


def test_undecodable_image_is_400(client, monkeypatch):
    from app.parser.extract import UnsupportedImage

    async def bad(image, mime):
        raise UnsupportedImage("truncated")

    monkeypatch.setattr(mocks.parser, "parse_prescription", staticmethod(bad))
    err(upload(client), 400, "unsupported_image")


def test_rejected_images_do_not_use_up_the_rate_limit(client, mock_mode):
    mock_mode.parse_rate_limit_per_hour = 1
    mock_mode.max_upload_mb = 1
    ip = {"CF-Connecting-IP": "203.0.113.9"}
    err(upload(client, b"not an image", headers=ip), 400, "unsupported_image")
    err(upload(client, PNG + b"\x00" * (1024 * 1024), headers=ip), 413, "image_too_large")
    ok(upload(client, headers=ip))
    err(upload(client, headers=ip), 429, "rate_limited")


def test_typed_word_counts(client):
    order = ok(client.post("/api/orders/text", json={"text": "two strips of dolo and ORS"}))
    assert [i.quantity_packs for i in order.items] == [2, 1]
    assert order.total_inr == round(2 * 33.6 + 22.0, 2)
