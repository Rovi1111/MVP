"""Настройки организации: значения из БД перекрывают значения по умолчанию из .env."""

from dataclasses import dataclass, fields
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import InvalidDataError
from app.models import User
from app.repositories.settings import SettingRepository
from app.services.audit import log_action

_SECRET_KEYS = {"smtp_password"}


@dataclass
class OrgSettings:
    ollama_url: str
    ollama_model: str
    ollama_timeout: float
    ai_auto_run: bool
    plan_fact_threshold: Decimal  # порог существенного отклонения, %
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_from: str
    smtp_tls: bool

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)


def _defaults() -> dict:
    env = get_settings()
    return {
        "ollama_url": env.ollama_url,
        "ollama_model": env.ollama_model,
        "ollama_timeout": env.ollama_timeout,
        "ai_auto_run": False,
        "plan_fact_threshold": Decimal("10"),
        "smtp_host": env.smtp_host,
        "smtp_port": env.smtp_port,
        "smtp_user": env.smtp_user,
        "smtp_password": env.smtp_password,
        "smtp_from": env.smtp_from,
        "smtp_tls": env.smtp_tls,
    }


def _convert(key: str, raw, target_type):
    """Приводит значение из формы/БД к типу поля; ошибки — понятным текстом."""
    try:
        if target_type is bool:
            if isinstance(raw, bool):
                return raw
            return str(raw).strip().lower() in ("1", "true", "on", "yes", "да")
        if target_type is int:
            return int(str(raw).strip())
        if target_type is float:
            return float(str(raw).strip().replace(",", "."))
        if target_type is Decimal:
            return Decimal(str(raw).strip().replace(",", "."))
    except (ValueError, InvalidOperation):
        raise InvalidDataError(f"Некорректное значение настройки {key}: «{raw}»") from None
    return str(raw).strip()


def _validate(values: dict) -> None:
    if "ollama_url" in values and not values["ollama_url"].startswith(("http://", "https://")):
        raise InvalidDataError("URL Ollama должен начинаться с http:// или https://")
    if "ollama_model" in values and not values["ollama_model"]:
        raise InvalidDataError("Название модели не может быть пустым")
    if "ollama_timeout" in values and not 1 <= values["ollama_timeout"] <= 3600:
        raise InvalidDataError("Таймаут Ollama должен быть от 1 до 3600 секунд")
    if "plan_fact_threshold" in values and not 0 <= values["plan_fact_threshold"] <= 1000:
        raise InvalidDataError("Порог отклонения должен быть от 0 до 1000 %")
    if "smtp_port" in values and not 1 <= values["smtp_port"] <= 65535:
        raise InvalidDataError("Порт SMTP должен быть от 1 до 65535")


def get_org_settings(db: Session, org_id: int) -> OrgSettings:
    values = _defaults()
    stored = SettingRepository(db, org_id).as_dict()
    for field in fields(OrgSettings):
        if field.name in stored:
            values[field.name] = _convert(field.name, stored[field.name], field.type)
    return OrgSettings(**values)


def update_org_settings(db: Session, actor: User, changes: dict) -> OrgSettings:
    types = {f.name: f.type for f in fields(OrgSettings)}
    unknown = set(changes) - set(types)
    if unknown:
        raise InvalidDataError(f"Неизвестные настройки: {', '.join(sorted(unknown))}")
    converted = {key: _convert(key, value, types[key]) for key, value in changes.items()}
    _validate(converted)
    repo = SettingRepository(db, actor.org_id)
    for key, value in converted.items():
        repo.set(key, str(value))
    logged = {k: ("***" if k in _SECRET_KEYS else str(v)) for k, v in converted.items()}
    log_action(db, actor, "update", "settings", None, logged)
    db.commit()
    return get_org_settings(db, actor.org_id)
