"""Пользовательские типы колонок."""

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import BigInteger
from sqlalchemy.types import TypeDecorator

KOPECK = Decimal("0.01")


def to_money(value) -> Decimal:
    """Приводит число к Decimal с точностью до копеек."""
    return Decimal(str(value)).quantize(KOPECK, rounding=ROUND_HALF_UP)


class Money(TypeDecorator):
    """Денежная сумма: в Python — Decimal, в БД — целое число копеек.

    Целые копейки одинаково точно хранятся и суммируются в SQLite и PostgreSQL
    (SQLite не имеет настоящего DECIMAL и хранил бы суммы как float).
    """

    impl = BigInteger
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return int(to_money(value) * 100)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return (Decimal(value) / 100).quantize(KOPECK)
