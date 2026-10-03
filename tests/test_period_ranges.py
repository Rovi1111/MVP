from datetime import date

import pytest

from app.services.periods import PeriodError, PeriodRange, parse_range, whole_months


@pytest.mark.parametrize(
    ("text", "start", "end", "label"),
    [
        ("2025-01-15", date(2025, 1, 15), date(2025, 1, 15), "15.01.2025"),
        ("2025-02", date(2025, 2, 1), date(2025, 2, 28), "февраль 2025"),
        ("2024-02", date(2024, 2, 1), date(2024, 2, 29), "февраль 2024"),
        ("2025-Q1", date(2025, 1, 1), date(2025, 3, 31), "1 кв. 2025"),
        ("4 кв 2025", date(2025, 10, 1), date(2025, 12, 31), "4 кв. 2025"),
        ("2025", date(2025, 1, 1), date(2025, 12, 31), "2025 год"),
        ("2025-01-10..2025-02-20", date(2025, 1, 10), date(2025, 2, 20), "10.01.2025 — 20.02.2025"),
        ("2025-01..2025-03", date(2025, 1, 1), date(2025, 3, 31), "01.01.2025 — 31.03.2025"),
        ("2024-Q4 .. 2025-Q1", date(2024, 10, 1), date(2025, 3, 31), "01.10.2024 — 31.03.2025"),
    ],
)
def test_parse_range(text, start, end, label):
    assert parse_range(text) == PeriodRange(start, end, label)


@pytest.mark.parametrize("text", ["", None, "когда-нибудь", "2025-03..2025-01", "2025-13", "1800"])
def test_parse_range_errors(text):
    with pytest.raises(PeriodError):
        parse_range(text)


def test_whole_months():
    assert whole_months(parse_range("2025-01-10..2025-02-20")) == PeriodRange(
        date(2025, 1, 1), date(2025, 2, 28), "01.01.2025 — 28.02.2025"
    )
    quarter = parse_range("2025-Q1")
    assert whole_months(quarter) is quarter
