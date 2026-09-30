"""ParsedLine -> SKU: trigram candidates, then an LLM re-rank only when ambiguous."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from psycopg import AsyncConnection

from app import catalog
from app.contracts import SKU, MatchCandidate, MatchResult, ParsedLine
from app.core import llm
from app.core.config import get_settings
from app.parser.models import RerankChoice
from app.parser.normalize import strength_numbers
from app.parser.prompts import RERANK_SYSTEM

log = logging.getLogger(__name__)

TOP_K = 5
CONFIDENT_SCORE = 0.85
CONFIDENT_MARGIN = 0.1
# A re-ranked pick whose strength and form agree with the line (checked in code) is
# treated as confident, provided the trigram score shows it is the same name at all.
AGREEMENT_FLOOR = 0.6


@dataclass
class MatchOutcome:
    result: MatchResult
    cost_usd: float | None = None
    latency_ms: int = 0


def search_query(line: ParsedLine) -> str:
    return " ".join(part for part in (line.drug, line.strength) if part)


def strength_agrees(line: ParsedLine, sku: SKU) -> bool | None:
    """True when every number in the line's strength appears in the SKU; None if unknown."""
    wanted = strength_numbers(line.strength)
    if not wanted:
        return None
    have = set(strength_numbers(sku.brand_name))
    for salt in sku.composition:
        have.update(strength_numbers(salt.strength))
    return all(n in have for n in wanted)


def form_agrees(line: ParsedLine, sku: SKU) -> bool | None:
    if line.form is None:
        return None
    if line.form == sku.form:
        return True
    liquid = {"syrup", "suspension"}
    return line.form in liquid and sku.form in liquid


def agrees(line: ParsedLine, sku: SKU) -> bool:
    """Strength and form both agree, or are unknown on the line (never both unknown)."""
    s, f = strength_agrees(line, sku), form_agrees(line, sku)
    if s is False or f is False:
        return False
    return s is True or f is True


def is_confident(candidates: list[MatchCandidate]) -> bool:
    if not candidates:
        return False
    top = candidates[0].score
    second = candidates[1].score if len(candidates) > 1 else 0.0
    return top >= CONFIDENT_SCORE and top - second >= CONFIDENT_MARGIN


def _fallback(line: ParsedLine, candidates: list[MatchCandidate], why: str) -> MatchResult:
    """No re-rank available: take the best-scoring candidate that agrees, else the top one."""
    top = candidates[0]
    near = [c for c in candidates if c.score >= top.score - CONFIDENT_MARGIN]
    pick = next((c for c in near if agrees(line, c.sku)), top)
    return MatchResult(
        sku=pick.sku,
        score=pick.score,
        candidates=candidates,
        reranked=False,
        reason=f"{why}; took the best trigram match",
    )


def _describe_candidate(i: int, c: MatchCandidate) -> str:
    return json.dumps(
        {
            "number": i,
            "brand_name": c.sku.brand_name,
            "form": c.sku.form,
            "pack": c.sku.pack_label,
            "composition": c.sku.composition_key,
        },
        ensure_ascii=False,
    )


def rerank_messages(line: ParsedLine, candidates: list[MatchCandidate]) -> list[dict]:
    as_read = {
        "raw_text": line.raw_text,
        "drug": line.drug,
        "strength": line.strength,
        "form": line.form,
    }
    body = "Line as read:\n" + json.dumps(as_read, ensure_ascii=False) + "\n\nCandidates:\n"
    body += "\n".join(_describe_candidate(i, c) for i, c in enumerate(candidates, start=1))
    return [{"role": "system", "content": RERANK_SYSTEM}, {"role": "user", "content": body}]


async def rerank(
    line: ParsedLine, candidates: list[MatchCandidate], model: str
) -> tuple[MatchResult, float | None, int]:
    result = await llm.complete_json(model, rerank_messages(line, candidates), RerankChoice)
    choice = RerankChoice.model_validate(result.data)
    if choice.choice is None or not 1 <= choice.choice <= len(candidates):
        match = MatchResult(sku=None, score=0.0, candidates=candidates, reranked=True, reason=choice.reason)
        return match, result.cost_usd, result.latency_ms
    picked = candidates[choice.choice - 1]
    score = picked.score
    if score >= AGREEMENT_FLOOR and agrees(line, picked.sku):
        score = max(score, CONFIDENT_SCORE)
    match = MatchResult(
        sku=picked.sku, score=score, candidates=candidates, reranked=True, reason=choice.reason
    )
    return match, result.cost_usd, result.latency_ms


async def match_line_detailed(
    conn: AsyncConnection, line: ParsedLine, *, rerank_model: str | None = None
) -> MatchOutcome:
    if not line.drug:
        return MatchOutcome(
            MatchResult(sku=None, score=0.0, candidates=[], reranked=False, reason="drug name unreadable")
        )
    candidates = await catalog.search(conn, search_query(line), limit=TOP_K)
    candidates = sorted(candidates, key=lambda c: c.score, reverse=True)[:TOP_K]
    if not candidates:
        return MatchOutcome(
            MatchResult(sku=None, score=0.0, candidates=[], reranked=False, reason="no catalog match")
        )
    if is_confident(candidates):
        top = candidates[0]
        return MatchOutcome(MatchResult(sku=top.sku, score=top.score, candidates=candidates, reranked=False))

    model = rerank_model or get_settings().rerank_model
    if not model:
        return MatchOutcome(_fallback(line, candidates, "ambiguous match, re-rank model not set"))
    try:
        result, cost, latency = await rerank(line, candidates, model)
    except llm.LLMError as exc:
        log.warning("re-rank failed, falling back to trigram order: %s", exc)
        return MatchOutcome(_fallback(line, candidates, "ambiguous match, re-rank failed"))
    return MatchOutcome(result, cost, latency)
