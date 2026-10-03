"""Источник данных: ручной ввод (форма или JSON)."""

from collections.abc import Mapping, Sequence

from app.datasources.base import DataSource, RawRow, SourceError

_FIELDS = ("period", "category", "amount", "cost_center")


class ManualSource(DataSource):
    code = "manual"

    def __init__(self, rows: Sequence[Mapping]):
        self.rows = rows

    @property
    def label(self) -> str:
        return "Ручной ввод"

    def fetch(self) -> list[RawRow]:
        if not isinstance(self.rows, Sequence) or isinstance(self.rows, str | bytes):
            raise SourceError("Ожидается список строк (rows)")
        result: list[RawRow] = []
        for index, item in enumerate(self.rows, start=1):
            if not isinstance(item, Mapping):
                raise SourceError(f"Строка {index}: ожидается объект с полями {', '.join(_FIELDS)}")
            values = {f: (None if item.get(f) in ("", None) else item.get(f)) for f in _FIELDS}
            if all(v is None for v in values.values()):
                continue
            result.append(RawRow(row=index, **values))
        if not result:
            raise SourceError("Нет ни одной заполненной строки")
        return result
