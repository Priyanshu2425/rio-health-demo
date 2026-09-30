"""Deterministic normalization of what the vision model transcribed.

The model copies frequency and duration as written; the numbers are computed here, so
they are reproducible and testable (DECISIONS.md #8: quantity is computed in code).
"""

from __future__ import annotations

import re
from datetime import date

from app.contracts import Form

# Latin/Indian abbreviations -> doses per day. None means "as needed", no fixed count.
_ABBREVIATIONS: dict[str, float | None] = {
    "od": 1,
    "qd": 1,
    "daily": 1,
    "once daily": 1,
    "once a day": 1,
    "hs": 1,
    "qhs": 1,
    "at bedtime": 1,
    "at night": 1,
    "bedtime": 1,
    "bd": 2,
    "bid": 2,
    "bds": 2,
    "twice daily": 2,
    "twice a day": 2,
    "tds": 3,
    "tid": 3,
    "thrice daily": 3,
    "thrice a day": 3,
    "three times a day": 3,
    "qid": 4,
    "qds": 4,
    "four times a day": 4,
    "sos": None,
    "prn": None,
    "as needed": None,
    "when required": None,
    "stat": None,
    "weekly": 1 / 7,
    "once a week": 1 / 7,
    "once weekly": 1 / 7,
    "alternate day": 0.5,
    "alternate days": 0.5,
    "every other day": 0.5,
    "eod": 0.5,
    "aod": 0.5,
}

_FRACTIONS = {"½": 0.5, "1/2": 0.5, "¼": 0.25, "1/4": 0.25, "¾": 0.75, "3/4": 0.75}
_SLOT = r"(?:\d+(?:\.\d+)?|½|¼|¾|1/2|1/4|3/4)"
_SLOT_PATTERN = re.compile(rf"(?<![\d/]){_SLOT}(?:\s*[-–—+]\s*{_SLOT}){{2,3}}(?![\d/])")
_HOURLY = re.compile(r"(?:q\s*(\d{1,2})\s*h(?:rs?|ourly)?|(\d{1,2})\s*(?:-\s*)?(?:hourly|hrly|hrs?\b|h\b))")
_TIMES_A_DAY = re.compile(r"(\d)\s*(?:x|times)\s*(?:a|per|/)?\s*(?:day|daily|d\b)")


def _slot_value(token: str) -> float:
    token = token.strip()
    if token in _FRACTIONS:
        return _FRACTIONS[token]
    return float(token)


def doses_per_day(frequency: str | None) -> float | None:
    """'1-0-1' -> 2, 'TDS' -> 3, '1-1-1-1' -> 4, 'SOS' -> None, 'q8h' -> 3.

    Returns None when the frequency is missing, as-needed or not understood.
    """
    if not frequency:
        return None
    text = frequency.lower().strip()

    slots = _SLOT_PATTERN.search(text)
    if slots:
        parts = re.split(r"\s*[-–—+]\s*", slots.group(0))
        total = sum(_slot_value(p) for p in parts)
        return total if total > 0 else None

    hourly = _HOURLY.search(text)
    if hourly:
        hours = int(hourly.group(1) or hourly.group(2))
        if 1 <= hours <= 24:
            return round(24 / hours, 2)

    times = _TIMES_A_DAY.search(text)
    if times:
        return float(times.group(1))

    cleaned = re.sub(r"[^a-z ]+", " ", text.replace(".", ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    for phrase in sorted(_ABBREVIATIONS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(phrase)}\b", cleaned):
            value = _ABBREVIATIONS[phrase]
            return float(value) if value is not None else None
    return None


_UNIT_DAYS = {
    "d": 1,
    "day": 1,
    "days": 1,
    "dys": 1,
    "w": 7,
    "wk": 7,
    "wks": 7,
    "week": 7,
    "weeks": 7,
    "m": 30,
    "mo": 30,
    "month": 30,
    "months": 30,
    "mth": 30,
    "mths": 30,
}
_WORD_NUMBERS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "fourteen": 14,
    "fifteen": 15,
    "thirty": 30,
}
# 5/7 = five days, 2/52 = two weeks, 1/12 = one month (British/Indian clinical shorthand).
_SLASH = re.compile(r"(\d+)\s*/\s*(7|52|12)\b")
_COUNT_UNIT = re.compile(r"(\d+)\s*(days?|dys|d|weeks?|wks?|wk|w|months?|mths?|mo|m)\b")


def duration_days(duration: str | None) -> int | None:
    """'x 5 days' -> 5, '5/7' -> 5, '2 weeks' -> 14, '1/12' -> 30, 'continue' -> None."""
    if not duration:
        return None
    text = duration.lower().strip()
    for word, number in _WORD_NUMBERS.items():
        text = re.sub(rf"\b{word}\b", str(number), text)

    slash = _SLASH.search(text)
    if slash:
        count, base = int(slash.group(1)), slash.group(2)
        return count * {"7": 1, "52": 7, "12": 30}[base]

    unit = _COUNT_UNIT.search(text)
    if unit:
        return int(unit.group(1)) * _UNIT_DAYS[unit.group(2)]

    bare = re.fullmatch(r"[x×*]?\s*(\d{1,3})", text)
    if bare:
        return int(bare.group(1))
    return None


_FORM_WORDS: list[tuple[str, Form]] = [
    ("tab", "tablet"),
    ("cap", "capsule"),
    ("syp", "syrup"),
    ("syr", "syrup"),
    ("susp", "suspension"),
    ("inj", "injection"),
    ("oint", "ointment"),
    ("crm", "cream"),
    ("cream", "cream"),
    ("gel", "gel"),
    ("drop", "drops"),
    ("gtt", "drops"),
    ("inh", "inhaler"),
    ("rotacap", "inhaler"),
    ("puff", "inhaler"),
    ("pdr", "powder"),
    ("powder", "powder"),
    ("sachet", "sachet"),
    ("sach", "sachet"),
]

FORMS: tuple[str, ...] = (
    "tablet",
    "capsule",
    "syrup",
    "suspension",
    "injection",
    "cream",
    "ointment",
    "gel",
    "drops",
    "inhaler",
    "powder",
    "sachet",
    "other",
)


def form_from_text(text: str | None) -> Form | None:
    """Map 'Tab.', 'Cap', 'Syp', 'Inj' etc. to a Form, or None."""
    if not text:
        return None
    lowered = text.lower().strip()
    if lowered in FORMS:
        return lowered  # type: ignore[return-value]
    if lowered in ("t", "t."):
        return "tablet"
    if lowered in ("c", "c."):
        return "capsule"
    for prefix, form in _FORM_WORDS:
        if re.search(rf"\b{prefix}", lowered):
            return form
    return None


def parse_date(value: str | None) -> date | None:
    """ISO 'YYYY-MM-DD' or Indian 'DD/MM/YYYY', 'DD-MM-YY', 'DD.MM.YYYY'. None if unsure."""
    if not value:
        return None
    text = value.strip()
    iso = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    try:
        if iso:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        dmy = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2}|\d{4})", text)
        if dmy:
            year = int(dmy.group(3))
            if year < 100:
                year += 2000
            return date(year, int(dmy.group(2)), int(dmy.group(1)))
    except ValueError:
        return None
    return None


def strength_numbers(text: str | None) -> list[str]:
    """Numbers in a strength or name, e.g. '500/125 mg' -> ['500', '125'], '0.5mg' -> ['0.5']."""
    if not text:
        return []
    return [n.rstrip("0").rstrip(".") if "." in n else n for n in re.findall(r"\d+(?:\.\d+)?", text)]
