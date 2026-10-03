"""Подключение к БД: engine, фабрика сессий, базовый класс моделей."""

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str, **kwargs) -> Engine:
    """Создаёт engine. Вся SQLite-специфика приложения собрана здесь."""
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite":
        return create_engine(url, **kwargs)

    if parsed.database and parsed.database != ":memory:":
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
    kwargs.setdefault("connect_args", {"check_same_thread": False})
    engine = create_engine(url, **kwargs)

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


engine = make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI-зависимость: сессия на запрос."""
    with SessionLocal() as session:
        yield session
