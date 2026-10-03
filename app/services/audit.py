"""Запись в журнал действий."""

from sqlalchemy.orm import Session

from app.models import AuditLog, User
from app.repositories.audit import AuditRepository


def log_action(
    db: Session,
    user: User,
    action: str,
    entity: str = "",
    entity_id: int | str | None = None,
    details: dict | None = None,
) -> None:
    """Добавляет запись в текущую транзакцию; commit делает вызывающий код."""
    AuditRepository(db, user.org_id).add(
        AuditLog(
            user_id=user.id,
            user_login=user.login,
            action=action,
            entity=entity,
            entity_id=None if entity_id is None else str(entity_id),
            details=details,
        )
    )
