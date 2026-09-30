"""Prescription parsing and SKU matching. Owned by `feat/parser-eval`.

The signatures below are the contract other branches call. Replace the bodies; do not
change the signatures without a contracts branch.
"""

from psycopg import AsyncConnection

from app.contracts import MatchResult, ParsedLine, ParsedRx, Sample


async def parse_prescription(image: bytes, mime: str) -> ParsedRx:
    """Vision extract of one prescription image. No catalog knowledge.

    Raises app.core.llm.LLMError when the model fails or times out.
    """
    raise NotImplementedError


async def match_line(conn: AsyncConnection, line: ParsedLine) -> MatchResult:
    """Candidates from app.catalog.search, then an LLM re-rank only when ambiguous."""
    raise NotImplementedError


async def match_text(conn: AsyncConnection, text: str) -> list[tuple[str, MatchResult]]:
    """Split a typed request ('crocin and ORS') into items and match each.

    Returns (requested_text, result) pairs in the order the customer wrote them.
    """
    raise NotImplementedError


async def list_samples(conn: AsyncConnection) -> list[Sample]:
    """Demo prescriptions from the `samples` table, in display order."""
    raise NotImplementedError


async def load_sample(conn: AsyncConnection, sample_id: str) -> tuple[bytes, str, ParsedRx]:
    """(image bytes, mime type, cached parse) from the `samples` table.

    Raises KeyError for an unknown id.
    """
    raise NotImplementedError
