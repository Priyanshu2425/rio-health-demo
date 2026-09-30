"""Rule-based splitter for typed requests: 'crocin and 2 ORS, dolo' -> 3 items."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.contracts import ParsedLine
from app.parser.normalize import form_from_text

_SEPARATORS = re.compile(r"\s*(?:,|;|\n|\+|&|\band also\b|\balso\b|\band\b|\baur\b)\s*", re.IGNORECASE)
_FILLER = re.compile(
    r"^(?:(?:hi|hello|hey|please|pls|plz|kindly|can you|could you|i need|i want|need|want|"
    r"send|send me|get me|give me|deliver|order|i'd like|i would like|some|a|an|the)\b[\s,]*)+",
    re.IGNORECASE,
)
_TRAILING_FILLER = re.compile(r"[\s,.!?]*(?:please|pls|plz|thanks|thank you|asap)?[\s.!?]*$", re.IGNORECASE)
_WORD_COUNTS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "ten": 10}
_QUANTITY = re.compile(
    r"^(?P<n>\d{1,3}|one|two|three|four|five|six|ten)\s*(?:x\s*)?"
    r"(?:(?:strips?|packs?|packets?|boxes?|bottles?|tubes?|sachets?)\s*(?:of\s*)?)?(?=\S)",
    re.IGNORECASE,
)
_TRAILING_QUANTITY = re.compile(
    r"\s+(?:x\s*(?P<n>\d{1,3})|(?P<m>\d{1,3})\s*(?:strips?|packs?|bottles?))$", re.IGNORECASE
)
_FORM_PREFIX = re.compile(r"^(?:tab|tabs|tablet|cap|caps|capsule|syp|syrup|inj)\.?\s+", re.IGNORECASE)
_TRAILING_STRENGTH = re.compile(
    r"^(?P<drug>.*?[a-z].*?)\s*(?P<strength>\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml|%)?)$", re.IGNORECASE
)


@dataclass
class TextItem:
    requested_text: str  # as the customer wrote it
    drug: str  # name for the catalog search
    strength: str | None
    quantity: int | None  # the number the customer typed ("2 ORS", "2 strips of dolo"); unit unknown
    form: str | None


def split_request(text: str) -> list[TextItem]:
    items: list[TextItem] = []
    for part in _SEPARATORS.split(text):
        requested = _TRAILING_FILLER.sub("", part.strip())
        body = _FILLER.sub("", requested).strip()
        if not body:
            continue
        quantity = None
        q = _QUANTITY.match(body)
        if q and re.search(r"[a-z]", body[q.end() :], re.IGNORECASE):
            n = q.group("n").lower()
            quantity = _WORD_COUNTS.get(n) or int(n)
            body = body[q.end() :].strip()
        tq = _TRAILING_QUANTITY.search(body)
        if tq:
            quantity = int(tq.group("n") or tq.group("m"))
            body = body[: tq.start()].strip()
        form = form_from_text(body) if _FORM_PREFIX.match(body) else None
        body = _FORM_PREFIX.sub("", body).strip()
        strength = None
        s = _TRAILING_STRENGTH.match(body)
        if s:
            body, strength = s.group("drug").strip(), s.group("strength").strip()
        if not re.search(r"[a-z]", body, re.IGNORECASE):
            continue
        items.append(TextItem(requested.strip(), body, strength, quantity, form))
    return items


def to_parsed_line(i: int, item: TextItem) -> ParsedLine:
    return ParsedLine(
        line_no=i,
        raw_text=item.requested_text,
        drug=item.drug,
        strength=item.strength,
        form=item.form,  # type: ignore[arg-type]
        # ParsedLine.quantity means units written on a prescription; a typed "2" may mean
        # strips, so it is not passed through. The caller has it on TextItem if needed.
    )
