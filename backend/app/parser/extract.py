"""Vision extract: image -> one LLM call -> ParsedRx."""

from __future__ import annotations

import io
import re

from PIL import Image, ImageOps, UnidentifiedImageError

from app.contracts import ParsedLine, ParsedRx
from app.core import llm
from app.core.config import get_settings
from app.parser.models import RxExtraction, RxLine
from app.parser.normalize import doses_per_day, duration_days, form_from_text, parse_date
from app.parser.prompts import VISION_SYSTEM, VISION_USER

MAX_SIDE = 1600


class UnsupportedImage(ValueError):
    """The bytes are not an image Pillow can read."""


def prepare_image(image: bytes, max_side: int = MAX_SIDE) -> tuple[bytes, str]:
    """Apply EXIF rotation, downscale to <= max_side on the long side, re-encode as JPEG."""
    try:
        img = Image.open(io.BytesIO(image))
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise UnsupportedImage(f"cannot read image: {exc}") from exc
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85, optimize=True)
    return out.getvalue(), "image/jpeg"


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = re.sub(r"\s+", " ", value).strip(" .,;:-")
    return value or None


_TRAILING_STRENGTH = re.compile(
    r"^(?P<drug>.*?[A-Za-z].*?)\s+(?P<strength>\d+(?:\.\d+)?(?:\s*/\s*\d+)?\s*(?:mg|mcg|g|ml|iu|%)?)$",
    re.IGNORECASE,
)


def to_parsed_line(line_no: int, raw: RxLine) -> ParsedLine:
    drug = _clean(raw.drug)
    strength = _clean(raw.strength)
    if drug and not strength:
        # "Dolo 650" in the drug field: split the trailing strength off.
        m = _TRAILING_STRENGTH.match(drug)
        if m:
            drug, strength = m.group("drug").strip(), m.group("strength").strip()
    illegible = list(dict.fromkeys(raw.illegible_fields))
    if not drug and "drug" not in illegible:
        illegible.insert(0, "drug")
    frequency = _clean(raw.frequency)
    return ParsedLine(
        line_no=line_no,
        raw_text=raw.raw_text.strip(),
        drug=drug,
        strength=strength,
        form=raw.form or form_from_text(raw.form_as_written),
        frequency=frequency,
        doses_per_day=doses_per_day(frequency),
        duration_days=duration_days(raw.duration),
        quantity=raw.quantity if raw.quantity and raw.quantity > 0 else None,
        illegible_fields=illegible,
    )


def to_parsed_rx(extraction: RxExtraction, model: str, latency_ms: int, cost_usd: float | None) -> ParsedRx:
    lines = [
        to_parsed_line(i, raw) for i, raw in enumerate(extraction.lines, start=1) if raw.raw_text.strip()
    ]
    return ParsedRx(
        doctor_name=_clean(extraction.doctor_name),
        clinic_name=_clean(extraction.clinic_name),
        patient_name=_clean(extraction.patient_name),
        rx_date=parse_date(extraction.rx_date),
        lines=lines,
        model=model,
        latency_ms=latency_ms,
        cost_usd=cost_usd,
    )


async def parse_prescription(image: bytes, mime: str, *, model: str | None = None) -> ParsedRx:
    """Downscale, one vision call, map to ParsedRx. `model` overrides VISION_MODEL (eval)."""
    del mime  # re-encoded as JPEG below, whatever came in
    prepared, prepared_mime = prepare_image(image)
    model_id = model or get_settings().vision_model
    messages = [
        {"role": "system", "content": VISION_SYSTEM},
        {
            "role": "user",
            "content": [{"type": "text", "text": VISION_USER}, llm.image_part(prepared, prepared_mime)],
        },
    ]
    result = await llm.complete_json(model_id, messages, RxExtraction)
    extraction = RxExtraction.model_validate(result.data)
    return to_parsed_rx(extraction, result.model, result.latency_ms, result.cost_usd)
