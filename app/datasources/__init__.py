"""Источники данных. Новый коннектор = новый подкласс DataSource (см. README)."""

from app.datasources.base import DataSource, RawRow, SourceError
from app.datasources.excel import ExcelSource
from app.datasources.manual import ManualSource

__all__ = ["DataSource", "ExcelSource", "ManualSource", "RawRow", "SourceError"]
