from datetime import date

import pytest

from app.parser.normalize import doses_per_day, duration_days, form_from_text, parse_date, strength_numbers


@pytest.mark.parametrize(
    "frequency,expected",
    [
        ("1-0-1", 2),
        ("1-1-1", 3),
        ("0-0-1", 1),
        ("1-0-0", 1),
        ("1 - 0 - 1", 2),
        ("1–0–1", 2),
        ("1-1-1-1", 4),
        ("½-0-½", 1),
        ("1/2-0-1/2", 1),
        ("0-0-2", 2),
        ("OD", 1),
        ("od", 1),
        ("BD", 2),
        ("B.D.", 2),
        ("BID", 2),
        ("TDS", 3),
        ("t.d.s", 3),
        ("TID", 3),
        ("QID", 4),
        ("HS", 1),
        ("OD HS", 1),
        ("BD after food", 2),
        ("1-0-1 after food", 2),
        ("twice daily", 2),
        ("once daily", 1),
        ("q8h", 3),
        ("6 hourly", 4),
        ("3 times a day", 3),
        ("alternate day", 0.5),
        ("SOS", None),
        ("sos", None),
        ("PRN", None),
        ("STAT", None),
        ("", None),
        (None, None),
        ("as directed", None),
    ],
)
def test_doses_per_day(frequency, expected):
    got = doses_per_day(frequency)
    if expected is None:
        assert got is None
    else:
        assert got == pytest.approx(expected)


def test_weekly_is_fraction():
    assert doses_per_day("once weekly") == pytest.approx(1 / 7)


@pytest.mark.parametrize(
    "duration,expected",
    [
        ("x 5 days", 5),
        ("5 days", 5),
        ("5d", 5),
        ("x5d", 5),
        ("5/7", 5),
        ("x 3/7", 3),
        ("2/52", 14),
        ("1/12", 30),
        ("1 week", 7),
        ("x 2 weeks", 14),
        ("1 month", 30),
        ("five days", 5),
        ("10", 10),
        ("x 10", 10),
        ("continue", None),
        ("", None),
        (None, None),
    ],
)
def test_duration_days(duration, expected):
    assert duration_days(duration) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Tab.", "tablet"),
        ("T.", None),
        ("Cap", "capsule"),
        ("Syp.", "syrup"),
        ("Syr", "syrup"),
        ("Inj.", "injection"),
        ("Susp", "suspension"),
        ("tablet", "tablet"),
        ("Oint.", "ointment"),
        (None, None),
    ],
)
def test_form_from_text(text, expected):
    assert form_from_text(text) == expected


def test_parse_date():
    assert parse_date("2026-09-28") == date(2026, 9, 28)
    assert parse_date("28/09/2026") == date(2026, 9, 28)
    assert parse_date("28.9.26") == date(2026, 9, 28)
    assert parse_date("31/02/2026") is None
    assert parse_date("yesterday") is None


def test_strength_numbers():
    assert strength_numbers("500/125 mg") == ["500", "125"]
    assert strength_numbers("625") == ["625"]
    assert strength_numbers("0.50mg") == ["0.5"]
    assert strength_numbers(None) == []
