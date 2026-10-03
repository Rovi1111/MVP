"""Источник данных: файл XLSX / XLS / CSV."""

import csv
import io
from pathlib import PurePath

import pandas as pd

from app.datasources.base import DataSource, RawRow, SourceError

MAX_FILE_SIZE = 10 * 1024 * 1024

# Синонимы заголовков (сравнение без регистра и лишних пробелов)
COLUMN_SYNONYMS: dict[str, set[str]] = {
    "period": {"период", "дата", "месяц", "дата операции", "period", "date", "month"},
    "category": {
        "статья", "категория", "статья расходов", "статья затрат", "категория расходов",
        "наименование", "category", "article", "item", "expense category",
    },
    "amount": {
        "сумма", "сумма, руб", "сумма, руб.", "сумма руб", "стоимость", "расход", "факт",
        "план", "бюджет", "amount", "sum", "total", "value", "cost", "plan", "budget", "fact",
    },
    "cost_center": {
        "цфо", "центр затрат", "центр финансовой ответственности", "подразделение", "отдел",
        "cost center", "cost_center", "costcenter", "department",
    },
}  # fmt: skip
REQUIRED = {"period": "Период", "category": "Статья", "amount": "Сумма"}
_CSV_ENCODINGS = ("utf-8-sig", "cp1251")
_CSV_DELIMITERS = ";,\t|"


def _normalize_header(value) -> str:
    return " ".join(str(value).replace(" ", " ").split()).casefold()


def _is_empty(value) -> bool:
    return value is None or (not isinstance(value, str) and pd.isna(value)) or value == ""


class ExcelSource(DataSource):
    code = "excel"

    def __init__(self, content: bytes, file_name: str):
        self.content = content
        self.file_name = file_name

    @property
    def label(self) -> str:
        return self.file_name

    def fetch(self) -> list[RawRow]:
        frame = self._read_frame()
        columns = self._map_columns(frame)
        rows: list[RawRow] = []
        for index, record in enumerate(frame.itertuples(index=False), start=2):
            values = {
                field: None if _is_empty(record[pos]) else record[pos]
                for field, pos in columns.items()
            }
            if all(v is None or (isinstance(v, str) and not v.strip()) for v in values.values()):
                continue  # полностью пустая строка
            rows.append(RawRow(row=index, **values))
        if not rows:
            raise SourceError("Файл не содержит строк с данными")
        return rows

    def _read_frame(self) -> pd.DataFrame:
        if not self.content:
            raise SourceError("Файл пуст")
        if len(self.content) > MAX_FILE_SIZE:
            raise SourceError("Файл больше 10 МБ")
        suffix = PurePath(self.file_name).suffix.lower()
        try:
            if suffix == ".xlsx":
                return pd.read_excel(io.BytesIO(self.content), dtype=object, engine="openpyxl")
            if suffix == ".xls":
                return pd.read_excel(io.BytesIO(self.content), dtype=object, engine="xlrd")
            if suffix == ".csv":
                return self._read_csv()
        except SourceError:
            raise
        except Exception as exc:  # повреждённый файл, не тот формат и т. п.
            raise SourceError(f"Не удалось прочитать файл «{self.file_name}»: {exc}") from exc
        raise SourceError("Поддерживаются файлы XLSX, XLS и CSV")

    def _read_csv(self) -> pd.DataFrame:
        text = None
        for encoding in _CSV_ENCODINGS:
            try:
                text = self.content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise SourceError(
                "Не удалось определить кодировку CSV (ожидается UTF-8 или Windows-1251)"
            )
        header = text.split("\n", 1)[0]
        try:
            delimiter = csv.Sniffer().sniff(header, delimiters=_CSV_DELIMITERS).delimiter
        except csv.Error:
            delimiter = max(_CSV_DELIMITERS, key=header.count)
        # dtype=str: суммы вида «1 234,56» разбираем сами, без догадок pandas
        return pd.read_csv(
            io.StringIO(text),
            sep=delimiter,
            dtype=str,
            keep_default_na=False,
            skip_blank_lines=True,
        )

    def _map_columns(self, frame: pd.DataFrame) -> dict[str, int]:
        columns: dict[str, int] = {}
        for position, header in enumerate(frame.columns):
            normalized = _normalize_header(header)
            for field, synonyms in COLUMN_SYNONYMS.items():
                if normalized in synonyms and field not in columns:
                    columns[field] = position
        missing = [title for field, title in REQUIRED.items() if field not in columns]
        if missing:
            found = ", ".join(str(c) for c in frame.columns) or "нет"
            raise SourceError(
                f"В файле не найдены обязательные колонки: {', '.join(missing)}. "
                f"Найденные заголовки: {found}"
            )
        return columns
