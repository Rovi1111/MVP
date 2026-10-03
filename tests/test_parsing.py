from decimal import Decimal

import pytest

from app.services.parsing import AmountError, normalize_name, parse_amount


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1234, "1234.00"),
        (1234.5, "1234.50"),
        (0.1 + 0.2, "0.30"),
        ("1234", "1234.00"),
        ("1 234,56", "1234.56"),
        ("1 234,56", "1234.56"),
        ("1,234.56", "1234.56"),
        ("1.234,56", "1234.56"),
        ("1,234,567", "1234567.00"),
        ("12,5", "12.50"),
        ("-500", "-500.00"),
        ("−500,10", "-500.10"),
        ("(500)", "-500.00"),
        ("1 500 ₽", "1500.00"),
        ("2000 руб.", "2000.00"),
        ("10.005", "10.01"),
    ],
)
def test_parse_amount(value, expected):
    assert parse_amount(value) == Decimal(expected)


@pytest.mark.parametrize("value", ["abc", "", "12,3,4x", "1e5", float("nan"), float("inf"), True])
def test_parse_amount_errors(value):
    with pytest.raises(AmountError):
        parse_amount(value)


def test_normalize_name():
    assert normalize_name("  Сухой   КОРМ ") == "сухой корм"
    assert normalize_name("Учёт") == normalize_name("учет")
