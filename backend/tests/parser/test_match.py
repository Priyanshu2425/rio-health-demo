import pytest

from app import catalog, parser
from app.contracts import ParsedLine
from app.core import llm
from app.core.config import get_settings
from app.core.llm import LLMError
from app.parser import match

from . import fakes
from .fakes import AUGMENTIN_375, AUGMENTIN_625, AUGMENTIN_SYP, DOLO_650, PAN_40, FakeCatalog, FakeLLM


def line(drug, strength=None, form="tablet", raw=None):
    return ParsedLine(
        line_no=1, raw_text=raw or f"Tab {drug} {strength or ''}", drug=drug, strength=strength, form=form
    )


@pytest.fixture
def rerank_model(monkeypatch):
    monkeypatch.setattr(get_settings(), "rerank_model", "test/rerank")


def install(monkeypatch, table, *payloads):
    cat = FakeCatalog(table)
    fake = FakeLLM(*payloads)
    monkeypatch.setattr(catalog, "search", cat.search)
    monkeypatch.setattr(llm, "complete_json", fake.complete_json)
    return cat, fake


async def test_confident_match_skips_llm(monkeypatch, rerank_model):
    cat, fake = install(monkeypatch, {"pan 40": [(PAN_40, 0.95), (DOLO_650, 0.2)]})
    result = await parser.match_line(None, line("Pan", "40"))
    assert result.sku.sku_id == "pan40"
    assert result.score == 0.95
    assert result.reranked is False
    assert fake.calls == []
    assert cat.queries == ["Pan 40"]


async def test_close_scores_trigger_rerank(monkeypatch, rerank_model):
    table = {"augmentin 625": [(AUGMENTIN_375, 0.9), (AUGMENTIN_625, 0.88), (AUGMENTIN_SYP, 0.7)]}
    _, fake = install(monkeypatch, table, {"choice": 2, "reason": "625 = 500+125 tablet"})
    result = await parser.match_line(None, line("Augmentin", "625"))
    assert result.reranked is True
    assert result.sku.sku_id == "aug625"
    # strength 625 appears in the brand and the form agrees -> confident
    assert result.score == 0.88
    assert result.reason == "625 = 500+125 tablet"
    assert len(fake.calls) == 1
    assert fake.calls[0]["model"] == "test/rerank"
    prompt = fake.calls[0]["messages"][1]["content"]
    assert "Augmentin 625 Duo Tablet" in prompt and "Augmentin" in prompt


async def test_low_top_score_triggers_rerank_and_boost(monkeypatch, rerank_model):
    table = {"augmentin 625": [(AUGMENTIN_625, 0.7)]}
    install(monkeypatch, table, {"choice": 1, "reason": "same brand and strength"})
    result = await parser.match_line(None, line("Augmentin", "625"))
    assert result.reranked is True
    assert result.score == match.CONFIDENT_SCORE


async def test_rerank_pick_that_disagrees_keeps_trigram_score(monkeypatch, rerank_model):
    table = {"augmentin 625": [(AUGMENTIN_SYP, 0.7), (AUGMENTIN_375, 0.65)]}
    install(monkeypatch, table, {"choice": 1, "reason": "closest"})
    result = await parser.match_line(None, line("Augmentin", "625"))
    assert result.sku.sku_id == "augsyp"
    assert result.score == 0.7


async def test_rerank_none(monkeypatch, rerank_model):
    install(monkeypatch, {"zzz": [(PAN_40, 0.3)]}, {"choice": None, "reason": "no candidate is this drug"})
    result = await parser.match_line(None, line("Zzz"))
    assert result.sku is None
    assert result.score == 0.0
    assert result.reranked is True
    assert result.candidates[0].sku.sku_id == "pan40"


async def test_rerank_out_of_range_is_none(monkeypatch, rerank_model):
    install(monkeypatch, {"zzz": [(PAN_40, 0.3)]}, {"choice": 7, "reason": "?"})
    result = await parser.match_line(None, line("Zzz"))
    assert result.sku is None


async def test_rerank_failure_falls_back_to_agreeing_candidate(monkeypatch, rerank_model):
    table = {"augmentin 625": [(AUGMENTIN_375, 0.8), (AUGMENTIN_625, 0.78)]}
    install(monkeypatch, table, LLMError("boom"))
    result = await parser.match_line(None, line("Augmentin", "625"))
    assert result.sku.sku_id == "aug625"
    assert result.reranked is False
    assert "re-rank failed" in result.reason


async def test_no_rerank_model_falls_back(monkeypatch):
    monkeypatch.setattr(get_settings(), "rerank_model", "")
    table = {"augmentin 625": [(AUGMENTIN_375, 0.8), (AUGMENTIN_625, 0.78)]}
    _, fake = install(monkeypatch, table)
    result = await parser.match_line(None, line("Augmentin", "625"))
    assert result.sku.sku_id == "aug625"
    assert fake.calls == []


async def test_unreadable_drug_no_search(monkeypatch, rerank_model):
    cat, _ = install(monkeypatch, {})
    result = await parser.match_line(None, line(None, "40"))
    assert result.sku is None and result.score == 0
    assert cat.queries == []


async def test_no_candidates(monkeypatch, rerank_model):
    install(monkeypatch, {})
    result = await parser.match_line(None, line("Unknownium"))
    assert result.sku is None
    assert result.reason == "no catalog match"


async def test_match_text_splits_and_matches(monkeypatch, rerank_model):
    table = {"dolo 650": [(DOLO_650, 0.97)], "pan 40": [(PAN_40, 0.95)]}
    install(monkeypatch, table)
    pairs = await parser.match_text(None, "dolo 650 and 2 pan 40")
    assert [(t, r.sku.sku_id) for t, r in pairs] == [("dolo 650", "dolo650"), ("2 pan 40", "pan40")]


def test_agreement_rules():
    assert match.strength_agrees(line("Augmentin", "625"), AUGMENTIN_625) is True
    assert match.strength_agrees(line("Augmentin", "500/125"), AUGMENTIN_625) is True
    assert match.strength_agrees(line("Augmentin", "625"), AUGMENTIN_375) is False
    assert match.strength_agrees(line("Augmentin"), AUGMENTIN_375) is None
    assert match.form_agrees(line("Augmentin", form="syrup"), AUGMENTIN_SYP) is True
    assert match.agrees(line("Augmentin", form=None), AUGMENTIN_625) is False  # nothing to check


async def test_fallback_prefers_brand_without_extra_words(monkeypatch):
    monkeypatch.setattr(get_settings(), "rerank_model", "")
    kid = fakes.sku("kid", "Montair LC Kid", "tablet", [("levocetirizine", "2.5mg"), ("montelukast", "4mg")])
    adult = fakes.sku("lc", "Montair-LC", "tablet", [("levocetirizine", "5mg"), ("montelukast", "10mg")])
    install(monkeypatch, {"montair lc": [(kid, 0.8), (adult, 0.75)]})
    result = await parser.match_line(None, line("Montair LC"))
    assert result.sku.sku_id == "lc"


DOLO_SUSP = fakes.sku("dolo", "Dolo", "suspension", [("paracetamol", "125mg")], rx=False)
DOLO_MF = fakes.sku("dolomf", "Dolo-MF", "suspension", [("mefenamic acid", "50mg"), ("paracetamol", "125mg")])
DOLO_250 = fakes.sku("dolo250", "Dolo 250", "suspension", [("paracetamol", "250mg")], rx=False)
DOLO_500 = fakes.sku("dolo500", "Dolo 500", "tablet", [("paracetamol", "500mg")], rx=False)
DOLO_TABLE = {
    "dolo": [(DOLO_SUSP, 1.0), (DOLO_MF, 0.81), (DOLO_650, 0.78), (DOLO_250, 0.78), (DOLO_500, 0.77)]
}


def ranks(monkeypatch, table):
    async def fake(conn, sku_ids):
        return {s: table[s] for s in sku_ids if s in table}

    monkeypatch.setattr(match, "popularity", fake)


async def test_typed_bare_brand_prefers_its_tablet(monkeypatch, rerank_model):
    _, fake = install(monkeypatch, DOLO_TABLE)
    ranks(monkeypatch, {"dolo650": 1, "dolo500": 7})
    [(text, result)] = await parser.match_text(None, "dolo")
    assert (text, result.sku.sku_id) == ("dolo", "dolo650")
    assert result.score == 0.78 and result.reranked is False
    assert "tablet" in result.reason
    assert fake.calls == []


async def test_typed_near_tied_tablets_go_to_the_better_known_one(monkeypatch, rerank_model):
    install(monkeypatch, DOLO_TABLE)
    ranks(monkeypatch, {"dolo650": 9, "dolo500": 2})
    [(_, result)] = await parser.match_text(None, "dolo")
    assert result.sku.sku_id == "dolo500"


async def test_typed_preference_ignores_brands_with_extra_words(monkeypatch, rerank_model):
    liquid = fakes.sku("allegra", "Allegra", "suspension", [("fexofenadine", "30mg")])
    combo = fakes.sku("allegram", "Allegra-M", "tablet", [("fexofenadine", "120mg"), ("montelukast", "10mg")])
    tab = fakes.sku("allegra120", "Allegra 120mg", "tablet", [("fexofenadine", "120mg")])
    install(monkeypatch, {"allegra": [(liquid, 1.0), (combo, 0.9), (tab, 0.79)]})
    ranks(monkeypatch, {"allegram": 1, "allegra120": 5})
    [(_, result)] = await parser.match_text(None, "allegra")
    assert result.sku.sku_id == "allegra120"


async def test_typed_strength_or_form_keeps_the_literal_match(monkeypatch, rerank_model):
    table = {
        "dolo 250": [(DOLO_250, 1.0), (DOLO_650, 0.7)],
        "dolo syrup": [(DOLO_SUSP, 0.5), (DOLO_650, 0.4)],
    }
    install(monkeypatch, table, {"choice": 1, "reason": "the suspension"})
    ranks(monkeypatch, {"dolo650": 1})
    pairs = await parser.match_text(None, "dolo 250, dolo syrup")
    assert [r.sku.sku_id for _, r in pairs] == ["dolo250", "dolo"]


async def test_typed_preference_needs_a_close_tablet(monkeypatch, rerank_model):
    install(monkeypatch, {"dolo": [(DOLO_SUSP, 1.0), (DOLO_650, 0.7)]})
    ranks(monkeypatch, {"dolo650": 1})
    [(_, result)] = await parser.match_text(None, "dolo")
    assert result.sku.sku_id == "dolo"  # 0.3 below the top is a different product


async def test_prescription_lines_keep_the_literal_match(monkeypatch, rerank_model):
    """match_line is unchanged; only typed requests get the tablet preference."""
    install(monkeypatch, DOLO_TABLE)
    ranks(monkeypatch, {"dolo650": 1})
    result = await parser.match_line(None, line("Dolo", form=None))
    assert result.sku.sku_id == "dolo"
