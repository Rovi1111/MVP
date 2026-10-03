"""Настройки приложения из переменных окружения и файла .env."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET_KEY = "dev-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Учёт расходов"
    # Смена СУБД — только эта строка (например, postgresql+psycopg://...)
    database_url: str = "sqlite:///./data/app.db"

    secret_key: str = DEV_SECRET_KEY
    session_max_age: int = 60 * 60 * 12  # секунд
    cookie_secure: bool = False
    auth_provider: str = "local"

    # Значения по умолчанию; администратор может переопределить их в UI (таблица settings)
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"
    ollama_timeout: float = 300.0

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_tls: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
