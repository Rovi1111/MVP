"""Время: в БД хранится UTC, пользователю показываем местное."""

from datetime import UTC, datetime


def to_local(value: datetime) -> datetime:
    """UTC из БД (в SQLite — без таймзоны) → местное время сервера."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone()
