from datetime import date, datetime

import pytest

from app.services.periods import PeriodError, parse_period


@pytest.mark.parametrize(
    ("value", "expected", "grain"),
    [
        ("2025-01-15", date(2025, 1, 15), "day"),
        ("15.01.2025", date(2025, 1, 15), "day"),
        ("15/01/2025", date(2025, 1, 15), "day"),
        ("2025-01-15 00:00:00", date(2025, 1, 15), "day"),
        (datetime(2025, 3, 7, 12, 30), date(2025, 3, 7), "day"),
        (date(2025, 3, 7), date(2025, 3, 7), "day"),
        (45672, date(2025, 1, 15), "day"),  # порядковый номер дня Excel
        ("45672", date(2025, 1, 15), "day"),
        ("2025-01", date(2025, 1, 1), "month"),
        ("01.2025", date(2025, 1, 1), "month"),
        ("1/2025", date(2025, 1, 1), "month"),
        ("янв 2025", date(2025, 1, 1), "month"),
        ("Январь 2025 г.", date(2025, 1, 1), "month"),
        ("мая 2025", date(2025, 5, 1), "month"),
        ("Dec 2024", date(2024, 12, 1), "month"),
        ("2025 сентябрь", date(2025, 9, 1), "month"),
        ("2025-Q1", date(2025, 1, 1), "quarter"),
        ("Q3 2025", date(2025, 7, 1), "quarter"),
        ("1 кв 2025", date(2025, 1, 1), "quarter"),
        ("2 кв. 2025 года", date(2025, 4, 1), "quarter"),
        ("IV квартал 2025", date(2025, 10, 1), "quarter"),
        ("3-й квартал 2025", date(2025, 7, 1), "quarter"),
    ],
)
def test_parse_period(value, expected, grain):
    parsed = parse_period(value)
    assert (parsed.date, parsed.grain) == (expected, grain)


@pytest.mark.parametrize(
    "value", ["", "   ", "вчера", "2025", "13.2025", "31.02.2025", "2025-Q5", "абв 2025", 7, True]
)
def test_parse_period_errors(value):
    with pytest.raises(PeriodError):
        parse_period(value)
