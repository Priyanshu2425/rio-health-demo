import io
from datetime import date

import pytest
from PIL import Image

from app import parser
from app.core import llm
from app.core.config import get_settings
from app.parser.extract import UnsupportedImage, prepare_image
from app.parser.models import RxExtraction

from .fakes import FakeLLM


def jpeg(w, h):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(buf, format="PNG")
    return buf.getvalue()


def line(raw, **kw):
    base = {
        "raw_text": raw,
        "form_as_written": None,
        "form": None,
        "drug": None,
        "strength": None,
        "frequency": None,
        "duration": None,
        "quantity": None,
        "instructions": None,
        "illegible_fields": [],
    }
    return base | kw


EXTRACTION = {
    "doctor_name": "Dr. A. Mehta ",
    "clinic_name": "Sunrise Clinic",
    "patient_name": "R. Sharma",
    "rx_date": "28/09/2026",
    "lines": [
        line(
            "Tab. Augmentin 625 1-0-1 x 5 days",
            form_as_written="Tab.",
            form="tablet",
            drug="Augmentin",
            strength="625",
            frequency="1-0-1",
            duration="x 5 days",
            instructions="after food",
        ),
        line(
            "Tab Pan 40 1-0-0 before food 5/7",
            form_as_written="Tab",
            drug="Pan",
            strength="40",
            frequency="1-0-0",
            duration="5/7",
        ),
        line(
            "Tab D?lo 650 SOS",
            form_as_written="Tab",
            form="tablet",
            drug="Dolo 650",
            frequency="SOS",
            illegible_fields=["drug"],
        ),
        line("Syp ?????? 5ml TDS", form_as_written="Syp", strength="5ml", frequency="TDS"),
        line("   "),
    ],
}


def test_prepare_image_downscales_and_reencodes():
    out, mime = prepare_image(jpeg(3200, 2400))
    assert mime == "image/jpeg"
    assert max(Image.open(io.BytesIO(out)).size) == 1600


def test_prepare_image_keeps_small():
    out, _ = prepare_image(jpeg(800, 600))
    assert Image.open(io.BytesIO(out)).size == (800, 600)


def test_prepare_image_rejects_junk():
    with pytest.raises(UnsupportedImage):
        prepare_image(b"not an image")


def test_llm_schema_is_strict_compatible():
    schema = RxExtraction.model_json_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    line_schema = schema["$defs"]["RxLine"]
    assert set(line_schema["required"]) == set(line_schema["properties"])


async def test_parse_maps_and_normalizes(monkeypatch):
    fake = FakeLLM(EXTRACTION, cost=0.002)
    monkeypatch.setattr(llm, "complete_json", fake.complete_json)
    monkeypatch.setattr(get_settings(), "vision_model", "test/vision")
    rx = await parser.parse_prescription(jpeg(2000, 1000), "image/png")

    assert fake.calls[0]["model"] == "test/vision"
    user = fake.calls[0]["messages"][1]["content"]
    assert user[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")

    assert rx.doctor_name == "Dr. A. Mehta"
    assert rx.rx_date == date(2026, 9, 28)
    assert rx.model == "test/vision" and rx.cost_usd == 0.002 and rx.latency_ms == 42
    assert len(rx.lines) == 4

    aug, pan, dolo, syp = rx.lines
    assert (aug.line_no, aug.drug, aug.strength, aug.form) == (1, "Augmentin", "625", "tablet")
    assert (aug.doses_per_day, aug.duration_days) == (2, 5)
    assert pan.form == "tablet"  # from 'Tab'
    assert (pan.doses_per_day, pan.duration_days) == (1, 5)
    assert (dolo.drug, dolo.strength, dolo.doses_per_day) == ("Dolo", "650", None)
    assert dolo.illegible_fields == ["drug"]
    assert syp.drug is None and syp.illegible_fields == ["drug"]
    assert syp.form == "syrup" and syp.doses_per_day == 3


async def test_parse_propagates_llm_error(monkeypatch):
    fake = FakeLLM(llm.LLMError("timeout"))
    monkeypatch.setattr(llm, "complete_json", fake.complete_json)
    with pytest.raises(llm.LLMError):
        await parser.parse_prescription(jpeg(100, 100), "image/png")


@pytest.mark.parametrize(
    "raw,qty,expected",
    [
        ("Tab Dolo 650 #10 SOS", 10, 10),
        ("Tab Dolo 650 2 strips", 2, None),
        ("Tab Dolo 650 No. 10 (1 strip)", 10, 10),
        ("Syp Calpol 1 bottle", 1, 1),
        ("Tab Pan 40 OD", None, None),
        ("Tab Pan 40 OD", 0, None),
    ],
)
def test_written_quantity_is_in_units(raw, qty, expected):
    from app.parser.extract import written_quantity
    from app.parser.models import RxLine

    assert written_quantity(RxLine.model_validate(line(raw, quantity=qty))) == expected
