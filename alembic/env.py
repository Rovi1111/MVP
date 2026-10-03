"""Окружение Alembic: метаданные и URL берутся из приложения."""

from logging.config import fileConfig

from alembic import context

from app import models  # noqa: F401  (регистрирует таблицы в Base.metadata)
from app.config import get_settings
from app.db import Base, make_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata
# sqlalchemy.url в alembic.ini пуст; непустое значение (в тестах) имеет приоритет
db_url = config.get_main_option("sqlalchemy.url") or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=db_url, target_metadata=target_metadata, literal_binds=True, render_as_batch=True
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = make_engine(db_url)
    with engine.connect() as connection:
        # render_as_batch: ALTER TABLE в SQLite выполняется пересозданием таблицы
        context.configure(
            connection=connection, target_metadata=target_metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
