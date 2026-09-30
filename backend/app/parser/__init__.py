"""Prescription parsing and SKU matching. Owned by `feat/parser-eval`.

The signatures below are the contract other branches call. Replace the bodies; do not
change the signatures without a contracts branch.
"""

from psycopg import AsyncConnection

from app.contracts import MatchResult, ParsedLine, ParsedRx, Sample
from app.parser import extract as _extract
from app.parser import match as _match
from app.parser import samples as _samples
from app.parser import split as _split


async def parse_prescription(image: bytes, mime: str) -> ParsedRx:
    """Vision extract of one prescription image. No catalog knowledge.

    Raises app.core.llm.LLMError when the model fails or times out.
    Raises app.parser.extract.UnsupportedImage (a ValueError) when Pillow cannot read it.
    """
    return await _extract.parse_prescription(image, mime)


async def match_line(conn: AsyncConnection, line: ParsedLine) -> MatchResult:
    """Candidates from app.catalog.search, then an LLM re-rank only when ambiguous."""
    return (await _match.match_line_detailed(conn, line)).result


async def match_text(conn: AsyncConnection, text: str) -> list[tuple[str, MatchResult]]:
    """Split a typed request ('crocin and ORS') into items and match each.

    Returns (requested_text, result) pairs in the order the customer wrote them.
    """
    pairs: list[tuple[str, MatchResult]] = []
    for i, item in enumerate(_split.split_request(text), start=1):
        outcome = await _match.match_line_detailed(conn, _split.to_parsed_line(i, item))
        pairs.append((item.requested_text, outcome.result))
    return pairs


async def list_samples(conn: AsyncConnection) -> list[Sample]:
    """Demo prescriptions from the `samples` table, in display order."""
    return await _samples.list_samples(conn)


async def load_sample(conn: AsyncConnection, sample_id: str) -> tuple[bytes, str, ParsedRx]:
    """(image bytes, mime type, cached parse) from the `samples` table.

    Raises KeyError for an unknown id.
    """
    return await _samples.load_sample(conn, sample_id)
