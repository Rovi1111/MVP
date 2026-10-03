"""Разбор сумм и нормализация названий (чистые функции)."""

import math
import re
from decimal import Decimal, InvalidOperation

from app.db_types import to_money

_RE_SPACES = re.compile(r"[\s   ']+")
_RE_CURRENCY = re.compile(r"(₽|руб\.?|р\.|rub)$", re.IGNORECASE)
_RE_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")


class AmountError(ValueError):
    pass


def normalize_name(name: str) -> str:
    """Ключ для сравнения названий: без регистра, лишних пробелов и различия е/ё."""
    return " ".join(str(name).split()).casefold().replace("ё", "е")


def clean_name(name) -> str:
    return " ".join(str(name).split())


def parse_amount(value) -> Decimal:
    """Преобразует значение ячейки в сумму: «1 234,56», «1,234.56», «(500)», 1234.5."""
    if isinstance(value, bool):
        raise AmountError(f"Сумма должна быть числом: «{value}»")
    if isinstance(value, Decimal):
        return to_money(value)
    if isinstance(value, int | float):
        if isinstance(value, float) and not math.isfinite(value):
            raise AmountError("Сумма должна быть числом")
        return to_money(value)

    text = _RE_SPACES.sub("", str(value)).replace("−", "-").replace("–", "-")
    text = _RE_CURRENCY.sub("", text)
    if text.startswith("(") and text.endswith(")"):  # бухгалтерская запись отрицательных
        text = "-" + text[1:-1]
    if "," in text and "." in text:
        # Десятичный разделитель — тот, что стоит правее; другой разделяет тысячи
        thousands = "," if text.rfind(".") > text.rfind(",") else "."
        text = text.replace(thousands, "").replace(",", ".")
    elif text.count(",") == 1:
        text = text.replace(",", ".")
    elif text.count(",") > 1 or text.count(".") > 1:
        text = text.replace(",", "").replace(".", "")

    if not _RE_NUMBER.match(text):
        raise AmountError(f"Сумма должна быть числом: «{value}»")
    try:
        return to_money(Decimal(text))
    except InvalidOperation:
        raise AmountError(f"Сумма должна быть числом: «{value}»") from None
