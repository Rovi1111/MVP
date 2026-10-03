"""Абстракция источника данных.

Любой источник (Excel, ручной ввод, в будущем — банк, 1С, эквайринг) отдаёт
одинаковые «сырые» строки. Валидация, сопоставление статей и запись в БД
(app/services/imports.py) от источника не зависят.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from app.errors import InvalidDataError


class SourceError(InvalidDataError):
    """Источник недоступен или отдал данные, которые невозможно разобрать."""


@dataclass(frozen=True)
class RawRow:
    """Строка источника до валидации. Значения — как пришли (строки, числа, даты)."""

    row: int  # номер строки в источнике, для сообщений об ошибках
    period: Any
    category: Any
    amount: Any
    cost_center: Any = None


class DataSource(ABC):
    #: код источника, сохраняется в uploads.source и expense_records.source
    code: str = ""

    @abstractmethod
    def fetch(self) -> list[RawRow]:
        """Возвращает строки источника; при невозможности — SourceError."""

    @property
    def label(self) -> str:
        """Имя для истории загрузок (например, имя файла)."""
        return ""
