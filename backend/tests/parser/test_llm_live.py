"""Live OpenRouter calls. Skipped unless RUN_LLM=1 (they cost money)."""

import pytest

from app import parser
from app.contracts import MatchCandidate, ParsedLine
from app.core.config import get_settings
from app.parser import match
from app.parser.extract import parse_prescription

from .fakes import AUGMENTIN_375, AUGMENTIN_625, AUGMENTIN_SYP

pytestmark = pytest.mark.llm


@pytest.fixture
def settings():
    s = get_settings()
    if not s.openrouter_api_key or not s.vision_model:
        pytest.skip("OPENROUTER_API_KEY / VISION_MODEL not set")
    return s


async def test_parse_typed_sample(settings):
    image, mime, cached = parser.load_sample("typed_clinic_3")
    rx = await parse_prescription(image, mime)
    drugs = " ".join((line.drug or "").lower() for line in rx.lines)
    assert len(rx.lines) == len(cached.lines)
    for expected in ("augmentin", "pan", "dolo"):
        assert expected in drugs
    assert rx.latency_ms > 0


async def test_rerank_picks_strength_match(settings):
    if not settings.rerank_model:
        pytest.skip("RERANK_MODEL not set")
    line = ParsedLine(
        line_no=1, raw_text="Tab Augmentin 625 1-0-1 x 5d", drug="Augmentin", strength="625", form="tablet"
    )
    cands = [MatchCandidate(sku=s, score=0.8) for s in (AUGMENTIN_375, AUGMENTIN_SYP, AUGMENTIN_625)]
    result, _, _ = await match.rerank(line, cands, settings.rerank_model)
    assert result.sku is not None and result.sku.sku_id == "aug625"
