"""Stand-ins for app.catalog, app.parser and app.forecast when RIO_USE_MOCKS=1.

Same function names and signatures as the real modules (the `conn` argument is accepted
and ignored), so `app.orders.deps` can swap one for the other. Data comes from
contracts/fixtures/, plus a handful of extra SKUs so typed orders show some variety:
"dolo and ORS" is an OTC cart, "augmentin" needs a prescription.
"""

from __future__ import annotations

import io
import json
import re
from functools import cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from pydantic import TypeAdapter
from rapidfuzz import fuzz

from app.contracts import (
    SKU,
    ForecastSummary,
    MatchCandidate,
    MatchResult,
    ParsedLine,
    ParsedRx,
    Salt,
    Sample,
    SkuForecast,
)

FIXTURES = Path(__file__).resolve().parents[3] / "contracts" / "fixtures"


def _fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


def _sku(sku_id, brand, maker, form, pack, label, mrp, salts, rx, schedule=None) -> SKU:
    comp = [Salt(name=n, strength=s) for n, s in salts]
    key = " + ".join(sorted(f"{s.name} {s.strength}" if s.strength else s.name for s in comp))
    return SKU(
        sku_id=sku_id,
        brand_name=brand,
        manufacturer=maker,
        form=form,
        pack_size=pack,
        pack_label=label,
        mrp_inr=mrp,
        composition=comp,
        composition_key=key,
        rx_only=rx,
        schedule=schedule,
    )


# Illustrative extras beyond the fixtures; prices are made up.
EXTRA_SKUS = [
    _sku("sku_crocin_500", "Crocin Advance 500", "GSK", "tablet", 15, "strip of 15 tablets", 24.5,
         [("paracetamol", "500mg")], False),
    _sku("sku_pacimol_650", "Pacimol 650", "Ipca", "tablet", 15, "strip of 15 tablets", 28.0,
         [("paracetamol", "650mg")], False),
    _sku("sku_cetzine_10", "Cetzine 10", "Dr. Reddy's", "tablet", 10, "strip of 10 tablets", 21.0,
         [("cetirizine", "10mg")], False),
    _sku("sku_okacet_10", "Okacet 10", "Cipla", "tablet", 10, "strip of 10 tablets", 18.0,
         [("cetirizine", "10mg")], False),
    _sku("sku_digene_gel", "Digene Gel Mint", "Abbott", "gel", 1, "bottle of 200 ml", 135.0,
         [("magnesium hydroxide", None), ("simethicone", None), ("aluminium hydroxide", None)], False),
    _sku("sku_vicks_rub", "Vicks VapoRub", "P&G", "ointment", 1, "jar of 25 ml", 99.0,
         [("menthol", None), ("camphor", None), ("eucalyptus oil", None)], False),
    _sku("sku_azithral_500", "Azithral 500", "Alembic", "tablet", 5, "strip of 5 tablets", 119.5,
         [("azithromycin", "500mg")], True, "H"),
    _sku("sku_azee_500", "Azee 500", "Cipla", "tablet", 5, "strip of 5 tablets", 98.0,
         [("azithromycin", "500mg")], True, "H"),
    _sku("sku_pantocid_40", "Pantocid 40", "Sun Pharma", "tablet", 15, "strip of 15 tablets", 172.0,
         [("pantoprazole", "40mg")], True, "H"),
    _sku("sku_montair_lc", "Montair LC", "Cipla", "tablet", 10, "strip of 10 tablets", 199.0,
         [("montelukast", "10mg"), ("levocetirizine", "5mg")], True, "H"),
]  # fmt: skip

# Common shorthand a customer types, mapped to a SKU.
ALIASES = {
    "ors": "sku_electral_21g",
    "electral": "sku_electral_21g",
    "paracetamol": "sku_dolo_650",
    "crocin": "sku_crocin_500",
    "antacid": "sku_digene_gel",
    "vicks": "sku_vicks_rub",
    "azithromycin": "sku_azithral_500",
    "pantoprazole": "sku_pan_40",
}


@cache
def _catalog() -> dict[str, SKU]:
    skus: dict[str, SKU] = {}
    for name in ("order_pending_review.json", "order_text_otc.json"):
        for item in _fixture(name)["items"]:
            for key in ("sku", "generic_alternative"):
                if item.get(key):
                    sku = SKU.model_validate(item[key])
                    skus[sku.sku_id] = sku
    for cand in _fixture("catalog_search.json"):
        sku = SKU.model_validate(cand["sku"])
        skus[sku.sku_id] = sku
    for sku in EXTRA_SKUS:
        skus.setdefault(sku.sku_id, sku)
    return skus


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9/ ]+", " ", text.lower()).strip()


def _score(query: str, sku: SKU) -> float:
    q = _norm(query)
    if not q:
        return 0.0
    if ALIASES.get(q) == sku.sku_id:
        return 0.93
    brand = _norm(sku.brand_name)
    by_brand = fuzz.WRatio(q, brand) / 100
    # A brand-name prefix ("augmentin" for "Augmentin 625 Duo") is a strong hit.
    if brand.split()[0] == q.split()[0]:
        by_brand = max(by_brand, 0.9 + 0.07 * (fuzz.token_set_ratio(q, brand) / 100))
    # Composition: each salt's name against the closest query word, tolerating spelling
    # variants (amoxicillin / amoxycillin, clavulanate / clavulanic acid).
    words = q.replace("/", " ").split()
    salts = [s.name.split()[0] for s in sku.composition]
    per_salt = [max(fuzz.ratio(salt, w) for w in words) / 100 for salt in salts]
    by_salt = 0.9 * sum(per_salt) / len(per_salt) if per_salt else 0.0
    # Strengths: a written number that matches a salt's strength helps, a mismatch hurts.
    numbers = {w for w in re.findall(r"\d+(?:\.\d+)?", q)}
    if numbers:
        strengths = {n for s in sku.composition for n in re.findall(r"\d+(?:\.\d+)?", s.strength or "")}
        by_salt += 0.05 if numbers & strengths else -0.1
    return round(min(1.0, max(by_brand, by_salt)), 3)


class catalog:
    @staticmethod
    async def search(conn: Any, query: str, limit: int = 5) -> list[MatchCandidate]:
        scored = [MatchCandidate(sku=s, score=_score(query, s)) for s in _catalog().values()]
        scored = [c for c in scored if c.score >= 0.4]
        scored.sort(key=lambda c: (-c.score, c.sku.mrp_inr))
        return scored[:limit]

    @staticmethod
    async def get_sku(conn: Any, sku_id: str) -> SKU | None:
        return _catalog().get(sku_id)

    @staticmethod
    async def cheapest_generic(conn: Any, sku: SKU) -> SKU | None:
        others = [
            s
            for s in _catalog().values()
            if s.composition_key == sku.composition_key
            and s.form == sku.form
            and s.sku_id != sku.sku_id
            and s.mrp_inr < sku.mrp_inr
        ]
        return min(others, key=lambda s: s.mrp_inr, default=None)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

MOCK_LATENCY_MS = 0


@cache
def _fixture_rx() -> ParsedRx:
    return ParsedRx.model_validate(_fixture("parsed_rx.json"))


@cache
def _fixture_scores() -> dict[str, tuple[str, float]]:
    """raw_text -> (sku_id, score) from the pending fixture, so the sample order
    reproduces the fixture's green / amber / red lines exactly."""
    out: dict[str, tuple[str, float]] = {}
    for item in _fixture("order_pending_review.json")["items"]:
        if item["parsed"] and item["sku"]:
            out[item["parsed"]["raw_text"]] = (item["sku"]["sku_id"], item["confidence"]["match_score"])
    return out


SAMPLE_LINES = {"typed_clinic_3": (1, 2, 3), "handwritten_2": (1, 3)}


def _sample_rx(sample_id: str) -> ParsedRx:
    keep = SAMPLE_LINES[sample_id]
    rx = _fixture_rx()
    lines = [rx.lines[n - 1].model_copy(update={"line_no": i}) for i, n in enumerate(keep, 1)]
    return rx.model_copy(update={"lines": lines, "model": "mock/cached-sample", "latency_ms": 0})


@cache
def _render(sample_id: str) -> bytes:
    rx = _sample_rx(sample_id)
    img = Image.new("RGB", (800, 560), (250, 248, 240))
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=24)
    header = [rx.clinic_name or "", rx.doctor_name or "", f"Patient: {rx.patient_name}  Date: {rx.rx_date}"]
    y = 30
    for text in header:
        draw.text((40, y), text, fill=(30, 30, 30), font=font)
        y += 34
    draw.line((40, y + 6, 760, y + 6), fill=(120, 120, 120), width=2)
    y += 40
    draw.text((40, y), "Rx", fill=(20, 20, 120), font=font)
    y += 36
    for line in rx.lines:
        draw.text((60, y), line.raw_text, fill=(10, 10, 60), font=font)
        y += 48
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _split(text: str) -> list[str]:
    parts = re.split(r",|;|\n|\+|&|\band\b|\bplus\b", text, flags=re.IGNORECASE)
    return [p.strip(" .") for p in parts if p.strip(" .")]


_FILLER = re.compile(
    r"^\s*(?:\d{1,2}\s*(?:x\s*)?)?(?:strips?|packs?|boxes|box|bottles?|sachets?|tablets?|tabs?)?"
    r"\s*(?:of\s+)?(?:some\s+|a\s+|an\s+)?",
    re.IGNORECASE,
)


def _query(requested: str) -> str:
    return _FILLER.sub("", requested).strip() or requested


class parser:
    @staticmethod
    async def parse_prescription(image: bytes, mime: str) -> ParsedRx:
        return _fixture_rx().model_copy(update={"model": "mock/vision", "latency_ms": MOCK_LATENCY_MS})

    @staticmethod
    async def match_line(conn: Any, line: ParsedLine) -> MatchResult:
        known = _fixture_scores().get(line.raw_text)
        if known is not None:
            sku = _catalog()[known[0]]
            cands = await catalog.search(conn, line.drug or line.raw_text)
            return MatchResult(sku=sku, score=known[1], candidates=cands, reranked=False)
        query = " ".join(x for x in (line.drug, line.strength) if x) or line.raw_text
        return await _match(conn, query)

    @staticmethod
    async def match_text(conn: Any, text: str) -> list[tuple[str, MatchResult]]:
        return [(part, await _match(conn, _query(part))) for part in _split(text)]

    @staticmethod
    def list_samples() -> list[Sample]:
        return TypeAdapter(list[Sample]).validate_python(_fixture("samples.json"))

    @staticmethod
    def load_sample(sample_id: str) -> tuple[bytes, str, ParsedRx]:
        if sample_id not in SAMPLE_LINES:
            raise KeyError(sample_id)
        return _render(sample_id), "image/png", _sample_rx(sample_id)


async def _match(conn: Any, query: str) -> MatchResult:
    cands = await catalog.search(conn, query)
    if not cands or cands[0].score < 0.6:
        best = cands[0].score if cands else 0.0
        return MatchResult(
            sku=None,
            score=best,
            candidates=cands,
            reranked=False,
            reason=f"nothing in the catalog for '{query}'",
        )
    return MatchResult(sku=cands[0].sku, score=cands[0].score, candidates=cands, reranked=False)


# ---------------------------------------------------------------------------
# Forecast
# ---------------------------------------------------------------------------


class forecast:
    @staticmethod
    async def get_summary(conn: Any) -> ForecastSummary:
        return ForecastSummary.model_validate(_fixture("forecast_summary.json"))

    @staticmethod
    async def get_sku_forecast(conn: Any, sku_id: str, area: str) -> SkuForecast | None:
        summary = await forecast.get_summary(conn)
        ref = next((s for s in summary.skus if s.sku_id == sku_id), None)
        if ref is None or area not in summary.areas:
            return None
        base = SkuForecast.model_validate(_fixture("sku_forecast.json"))
        return base.model_copy(update={"sku_id": ref.sku_id, "brand_name": ref.brand_name, "area": area})

    @staticmethod
    async def run(conn: Any) -> ForecastSummary:
        return await forecast.get_summary(conn)
